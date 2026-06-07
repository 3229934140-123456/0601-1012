import click
from ..database import (
    get_db, get_asset_by_no, update_asset, log_operation,
    update_asset_timestamp, query_assets
)


def _parse_asset_nos(ctx, param, value):
    if not value:
        return []
    if ',' in value:
        return [v.strip() for v in value.split(',') if v.strip()]
    return [value]


@click.command('assign')
@click.option('--asset-no', '-n', 'asset_nos', callback=_parse_asset_nos,
              help='资产编号，多个用逗号分隔')
@click.option('--file', '-f', 'file_path', type=click.Path(exists=True),
              help='从文件批量分配（CSV格式: asset_no,user_name）')
@click.option('--user', '-u', 'user_name', help='使用人')
@click.option('--department', '-d', help='所属部门')
@click.option('--operator', default='system', help='操作人')
@click.option('--remark', help='备注')
@click.option('--yes', '-y', is_flag=True, help='跳过确认')
def assign_cmd(asset_nos, file_path, user_name, department, operator, remark, yes):
    """批量分配资产使用人"""
    assignments = []

    if file_path:
        import csv
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                asset_no = row.get('asset_no') or row.get('资产编号')
                usr = row.get('user_name') or row.get('使用人') or user_name
                dept = row.get('department') or row.get('部门') or department
                if asset_no and usr:
                    assignments.append({
                        'asset_no': asset_no.strip(),
                        'user_name': usr.strip(),
                        'department': dept.strip() if dept else None
                    })
    elif asset_nos and user_name:
        for no in asset_nos:
            assignments.append({
                'asset_no': no,
                'user_name': user_name,
                'department': department
            })
    else:
        click.echo("错误: 请指定资产编号和使用人，或使用 --file 批量导入")
        return

    if not assignments:
        click.echo("没有可分配的资产")
        return

    if not yes:
        click.echo(f"将分配 {len(assignments)} 项资产:")
        for a in assignments[:5]:
            click.echo(f"  {a['asset_no']} -> {a['user_name']}"
                       f"{(' (' + a['department'] + ')') if a['department'] else ''}")
        if len(assignments) > 5:
            click.echo(f"  ... 还有 {len(assignments) - 5} 项")
        if not click.confirm("确认分配?", default=True):
            click.echo("已取消")
            return

    with get_db() as conn:
        success = 0
        failed = 0

        for item in assignments:
            asset = get_asset_by_no(conn, item['asset_no'])
            if not asset:
                click.echo(f"跳过: 资产 {item['asset_no']} 不存在")
                failed += 1
                continue

            update_data = {'user_name': item['user_name'], 'status': '在用'}
            if item['department']:
                update_data['department'] = item['department']
            if remark:
                update_data['remark'] = (asset['remark'] + '; ' if asset['remark'] else '') + remark

            update_asset(conn, item['asset_no'], update_data)
            update_asset_timestamp(conn, item['asset_no'])

            detail = f"分配给 {item['user_name']}"
            if item['department']:
                detail += f"（{item['department']}）"
            if remark:
                detail += f" | 备注: {remark}"

            log_operation(conn, item['asset_no'], '分配', operator, detail)
            success += 1

    click.echo(f"\n分配完成: 成功 {success} 个，失败 {failed} 个")


@click.command('return')
@click.option('--asset-no', '-n', 'asset_nos', callback=_parse_asset_nos,
              help='资产编号，多个用逗号分隔')
@click.option('--file', '-f', 'file_path', type=click.Path(exists=True),
              help='从文件批量归还（每行一个资产编号）')
@click.option('--operator', default='system', help='操作人')
@click.option('--remark', help='备注')
@click.option('--yes', '-y', is_flag=True, help='跳过确认')
def return_cmd(asset_nos, file_path, operator, remark, yes):
    """登记资产归还"""
    return_list = []

    if file_path:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    return_list.append(line)
    elif asset_nos:
        return_list = asset_nos
    else:
        click.echo("错误: 请指定资产编号，或使用 --file 批量导入")
        return

    if not return_list:
        click.echo("没有可归还的资产")
        return

    if not yes:
        click.echo(f"将归还 {len(return_list)} 项资产:")
        for no in return_list[:10]:
            click.echo(f"  {no}")
        if len(return_list) > 10:
            click.echo(f"  ... 还有 {len(return_list) - 10} 项")
        if not click.confirm("确认归还?", default=True):
            click.echo("已取消")
            return

    with get_db() as conn:
        success = 0
        failed = 0

        for asset_no in return_list:
            asset = get_asset_by_no(conn, asset_no)
            if not asset:
                click.echo(f"跳过: 资产 {asset_no} 不存在")
                failed += 1
                continue

            old_user = asset['user_name'] or '未知'

            update_data = {'user_name': '', 'status': '闲置'}
            if remark:
                update_data['remark'] = (asset['remark'] + '; ' if asset['remark'] else '') + remark

            update_asset(conn, asset_no, update_data)
            update_asset_timestamp(conn, asset_no)

            detail = f"归还，原使用人: {old_user}"
            if remark:
                detail += f" | 备注: {remark}"

            log_operation(conn, asset_no, '归还', operator, detail)
            success += 1

    click.echo(f"\n归还完成: 成功 {success} 个，失败 {failed} 个")


@click.command('transfer')
@click.option('--from-user', 'from_user', help='原使用人')
@click.option('--to-user', 'to_user', help='新使用人')
@click.option('--to-department', help='新部门')
@click.option('--operator', default='system', help='操作人')
@click.option('--remark', help='备注')
@click.option('--yes', '-y', is_flag=True, help='跳过确认')
def transfer_cmd(from_user, to_user, to_department, operator, remark, yes):
    """按使用人批量转移资产"""
    if not from_user or not to_user:
        click.echo("错误: 请指定原使用人和新使用人")
        return

    with get_db() as conn:
        assets = query_assets(conn, {'user_name': from_user, 'status': '在用'})

        if not assets:
            click.echo(f"未找到使用人 {from_user} 的在用资产")
            return

        if not yes:
            click.echo(f"将转移 {len(assets)} 项资产:")
            for a in assets[:5]:
                click.echo(f"  {a['asset_no']} - {a['name']}")
            if len(assets) > 5:
                click.echo(f"  ... 还有 {len(assets) - 5} 项")
            click.echo(f"\n从 {from_user} 转移到 {to_user}")
            if to_department:
                click.echo(f"部门变更为: {to_department}")
            if not click.confirm("确认转移?", default=True):
                click.echo("已取消")
                return

        success = 0
        for asset in assets:
            update_data = {'user_name': to_user}
            if to_department:
                update_data['department'] = to_department
            if remark:
                update_data['remark'] = (asset['remark'] + '; ' if asset['remark'] else '') + remark

            update_asset(conn, asset['asset_no'], update_data)
            update_asset_timestamp(conn, asset['asset_no'])

            detail = f"从 {from_user} 转移到 {to_user}"
            if to_department:
                detail += f"（{to_department}）"
            if remark:
                detail += f" | 备注: {remark}"

            log_operation(conn, asset['asset_no'], '转移', operator, detail)
            success += 1

    click.echo(f"\n转移完成: {success} 项资产")
