import click
from ..database import (
    get_db, get_asset_by_no, update_asset, log_operation,
    update_asset_timestamp, query_assets, ASSET_STATUS
)


DEPRECIATION_STATUSES = ['正常', '折旧中', '已提足折旧', '待评估']


def _parse_asset_nos(ctx, param, value):
    if not value:
        return []
    if ',' in value:
        return [v.strip() for v in value.split(',') if v.strip()]
    return [value]


@click.command('tag')
@click.option('--asset-no', '-n', 'asset_nos', callback=_parse_asset_nos,
              help='资产编号，多个用逗号分隔')
@click.option('--category', '-c', help='按类别生成标签')
@click.option('--department', '-d', help='按部门生成标签')
@click.option('--status', '-s', type=click.Choice(ASSET_STATUS), help='按状态生成标签')
@click.option('--template', '-t',
              type=click.Choice(['standard', 'simple', 'qr', 'detailed']),
              default='standard',
              help='标签模板')
@click.option('--output', '-o', help='输出到文件')
@click.option('--columns', type=int, default=2, help='每行标签数')
def tag_cmd(asset_nos, category, department, status, template, output, columns):
    """打印资产标签内容"""
    with get_db() as conn:
        if asset_nos:
            assets = []
            for no in asset_nos:
                asset = get_asset_by_no(conn, no)
                if asset:
                    assets.append(asset)
                else:
                    click.echo(f"警告: 资产 {no} 不存在，跳过")
        else:
            filters = {}
            if category:
                filters['category'] = category
            if department:
                filters['department'] = department
            if status:
                filters['status'] = status
            assets = query_assets(conn, filters)

    if not assets:
        click.echo("没有找到可生成标签的资产")
        return

    tags = []
    for asset in assets:
        if template == 'simple':
            tag = _simple_tag(asset)
        elif template == 'detailed':
            tag = _detailed_tag(asset)
        elif template == 'qr':
            tag = _qr_tag(asset)
        else:
            tag = _standard_tag(asset)
        tags.append(tag)

    if output:
        with open(output, 'w', encoding='utf-8') as f:
            for i in range(0, len(tags), columns):
                row = tags[i:i + columns]
                lines = max(len(t.split('\n')) for t in row)
                for line_idx in range(lines):
                    line_parts = []
                    for tag in row:
                        tag_lines = tag.split('\n')
                        if line_idx < len(tag_lines):
                            line_parts.append(tag_lines[line_idx])
                        else:
                            line_parts.append(' ' * len(tag_lines[0]))
                    f.write('  '.join(line_parts) + '\n')
                f.write('\n')
        click.echo(f"已生成 {len(assets)} 个标签，输出到 {output}")
    else:
        for tag in tags:
            click.echo(tag)
            click.echo()
        click.echo(f"共 {len(assets)} 个标签")


def _standard_tag(asset):
    width = 30
    border = '+' + '-' * (width - 2) + '+'
    empty = '|' + ' ' * (width - 2) + '|'

    def center(text, w=width - 2):
        if len(text) > w:
            text = text[:w - 3] + '...'
        pad = (w - len(text)) // 2
        return '|' + ' ' * pad + text + ' ' * (w - pad - len(text)) + '|'

    def left(text, w=width - 2):
        if len(text) > w:
            text = text[:w - 3] + '...'
        return '| ' + text + ' ' * (w - len(text) - 1) + '|'

    lines = [
        border,
        center('资产标签'),
        border,
        left(f"编号: {asset['asset_no']}"),
        left(f"名称: {asset['name']}"),
        left(f"类别: {asset['category']}"),
        left(f"部门: {asset['department'] or '-'}"),
        left(f"使用人: {asset['user_name'] or '-'}"),
        left(f"地点: {asset['location'] or '-'}"),
        border,
    ]
    return '\n'.join(lines)


def _simple_tag(asset):
    width = 25
    border = '+' + '-' * (width - 2) + '+'

    def center(text, w=width - 2):
        if len(text) > w:
            text = text[:w - 3] + '...'
        pad = (w - len(text)) // 2
        return '|' + ' ' * pad + text + ' ' * (w - pad - len(text)) + '|'

    def left(text, w=width - 2):
        if len(text) > w:
            text = text[:w - 3] + '...'
        return '| ' + text + ' ' * (w - len(text) - 1) + '|'

    lines = [
        border,
        center(asset['asset_no']),
        left(asset['name']),
        left(asset['category']),
        border,
    ]
    return '\n'.join(lines)


def _detailed_tag(asset):
    width = 35
    border = '+' + '-' * (width - 2) + '+'

    def center(text, w=width - 2):
        if len(text) > w:
            text = text[:w - 3] + '...'
        pad = (w - len(text)) // 2
        return '|' + ' ' * pad + text + ' ' * (w - pad - len(text)) + '|'

    def left(text, w=width - 2):
        if len(text) > w:
            text = text[:w - 3] + '...'
        return '| ' + text + ' ' * (w - len(text) - 1) + '|'

    price = f"{asset['purchase_price']:.2f} 元" if asset['purchase_price'] else '-'

    lines = [
        border,
        center('企业资产标签'),
        border,
        left(f"资产编号: {asset['asset_no']}"),
        left(f"资产名称: {asset['name']}"),
        left(f"资产类别: {asset['category']}"),
        left(f"品牌型号: {(asset['brand'] or '') + ' ' + (asset['model'] or '')}"),
        left(f"序列号: {asset['serial_no'] or '-'}"),
        left(f"所属部门: {asset['department'] or '-'}"),
        left(f"使用/保管人: {asset['user_name'] or '-'}"),
        left(f"存放地点: {asset['location'] or '-'}"),
        left(f"资产状态: {asset['status']}"),
        left(f"购入日期: {asset['purchase_date'] or '-'}"),
        left(f"购入价格: {price}"),
        border,
    ]
    return '\n'.join(lines)


def _qr_tag(asset):
    width = 28
    border = '+' + '-' * (width - 2) + '+'

    def center(text, w=width - 2):
        if len(text) > w:
            text = text[:w - 3] + '...'
        pad = (w - len(text)) // 2
        return '|' + ' ' * pad + text + ' ' * (w - pad - len(text)) + '|'

    qr_placeholder = [
        '|  ▓▓▓▓▓ ▓ ▓▓▓▓▓  |',
        '|  ▓   ▓  ▓ ▓   ▓  |',
        '|  ▓▓▓▓▓ ▓ ▓▓▓▓▓  |',
        '|  ▓ ▓  ▓▓  ▓ ▓   |',
        '|  ▓▓▓▓▓ ▓ ▓▓▓▓▓  |',
    ]

    lines = [
        border,
        center(asset['asset_no']),
        border,
    ]
    lines.extend(qr_placeholder)
    lines.append(border)
    lines.append(center(asset['name']))
    lines.append(border)
    return '\n'.join(lines)


@click.command('status')
@click.option('--asset-no', '-n', 'asset_nos', callback=_parse_asset_nos, required=True,
              help='资产编号，多个用逗号分隔')
@click.option('--set', '-s', 'new_status', type=click.Choice(ASSET_STATUS), required=True,
              help='设置状态')
@click.option('--operator', default='system', help='操作人')
@click.option('--remark', help='备注')
@click.option('--yes', '-y', is_flag=True, help='跳过确认')
def status_cmd(asset_nos, new_status, operator, remark, yes):
    """设置资产状态（闲置/在用/维修中/已报废）"""
    if not yes:
        click.echo(f"将把 {len(asset_nos)} 项资产状态设置为 '{new_status}'")
        for no in asset_nos[:10]:
            click.echo(f"  {no}")
        if len(asset_nos) > 10:
            click.echo(f"  ... 还有 {len(asset_nos) - 10} 项")
        if not click.confirm("确认修改?", default=True):
            click.echo("已取消")
            return

    with get_db() as conn:
        success = 0
        failed = 0

        for asset_no in asset_nos:
            asset = get_asset_by_no(conn, asset_no)
            if not asset:
                click.echo(f"跳过: 资产 {asset_no} 不存在")
                failed += 1
                continue

            old_status = asset['status']

            update_data = {'status': new_status}
            if remark:
                update_data['remark'] = (asset['remark'] + '; ' if asset['remark'] else '') + remark

            update_asset(conn, asset_no, update_data)
            update_asset_timestamp(conn, asset_no)

            detail = f"状态从 {old_status} 变更为 {new_status}"
            if remark:
                detail += f" | 备注: {remark}"

            log_operation(conn, asset_no, '状态变更', operator, detail)
            success += 1

    click.echo(f"\n状态变更完成: 成功 {success} 个，失败 {failed} 个")


@click.command('depreciation')
@click.option('--asset-no', '-n', 'asset_nos', callback=_parse_asset_nos, required=True,
              help='资产编号，多个用逗号分隔')
@click.option('--set', '-s', 'new_status', type=click.Choice(DEPRECIATION_STATUSES),
              required=True, help='设置折旧状态')
@click.option('--operator', default='system', help='操作人')
@click.option('--remark', help='备注')
def depreciation_cmd(asset_nos, new_status, operator, remark):
    """设置折旧状态"""
    with get_db() as conn:
        success = 0
        failed = 0

        for asset_no in asset_nos:
            asset = get_asset_by_no(conn, asset_no)
            if not asset:
                click.echo(f"跳过: 资产 {asset_no} 不存在")
                failed += 1
                continue

            old_status = asset['depreciation_status'] or '未设置'

            update_data = {'depreciation_status': new_status}
            if remark:
                update_data['remark'] = (asset['remark'] + '; ' if asset['remark'] else '') + remark

            update_asset(conn, asset_no, update_data)
            update_asset_timestamp(conn, asset_no)

            detail = f"折旧状态从 {old_status} 变更为 {new_status}"
            if remark:
                detail += f" | 备注: {remark}"

            log_operation(conn, asset_no, '折旧更新', operator, detail)
            success += 1

    click.echo(f"\n折旧状态更新完成: 成功 {success} 个，失败 {failed} 个")


@click.command('scrap')
@click.option('--asset-no', '-n', 'asset_nos', callback=_parse_asset_nos, required=True,
              help='资产编号，多个用逗号分隔')
@click.option('--operator', default='system', help='操作人')
@click.option('--reason', help='报废原因')
@click.option('--yes', '-y', is_flag=True, help='跳过确认')
def scrap_cmd(asset_nos, operator, reason, yes):
    """标记资产报废"""
    if not yes:
        click.echo(f"将报废 {len(asset_nos)} 项资产:")
        for no in asset_nos[:10]:
            click.echo(f"  {no}")
        if len(asset_nos) > 10:
            click.echo(f"  ... 还有 {len(asset_nos) - 10} 项")
        if not click.confirm("确认报废?", default=False):
            click.echo("已取消")
            return

    with get_db() as conn:
        success = 0
        failed = 0

        for asset_no in asset_nos:
            asset = get_asset_by_no(conn, asset_no)
            if not asset:
                click.echo(f"跳过: 资产 {asset_no} 不存在")
                failed += 1
                continue

            update_data = {'status': '已报废', 'user_name': ''}
            if reason:
                update_data['remark'] = (asset['remark'] + '; ' if asset['remark'] else '') + f'报废原因: {reason}'

            update_asset(conn, asset_no, update_data)
            update_asset_timestamp(conn, asset_no)

            detail = '资产报废'
            if reason:
                detail += f' | 原因: {reason}'

            log_operation(conn, asset_no, '报废', operator, detail)
            success += 1

    click.echo(f"\n报废完成: 成功 {success} 个，失败 {failed} 个")


@click.command('idle')
@click.option('--asset-no', '-n', 'asset_nos', callback=_parse_asset_nos,
              help='资产编号，多个用逗号分隔')
@click.option('--department', '-d', help='按部门筛选')
@click.option('--category', '-c', help='按类别筛选')
@click.option('--from-status', type=click.Choice(['在用', '维修中', '全部']), default='在用',
              help='从哪些状态的资产中筛选（默认在用）')
@click.option('--mark-idle', is_flag=True, help='执行标记为闲置操作（清空使用人）')
@click.option('--operator', default='system', help='操作人')
@click.option('--remark', help='闲置原因/备注')
@click.option('--yes', '-y', is_flag=True, help='跳过确认')
def idle_cmd(asset_nos, department, category, from_status, mark_idle, operator, remark, yes):
    """查看或将在用资产批量标记为闲置"""
    with get_db() as conn:
        target_assets = []

        if asset_nos:
            for no in asset_nos:
                asset = get_asset_by_no(conn, no)
                if asset:
                    if from_status == '全部' or asset['status'] == from_status:
                        target_assets.append(asset)
                else:
                    click.echo(f"警告: 资产 {no} 不存在，跳过")
        else:
            filters = {}
            if from_status != '全部':
                filters['status'] = from_status
            if department:
                filters['department'] = department
            if category:
                filters['category'] = category
            target_assets = query_assets(conn, filters)

    if not target_assets:
        click.echo("没有符合条件的资产")
        return

    click.echo(f"找到 {len(target_assets)} 项符合条件的资产"
               f"（状态: {from_status}）:")
    from tabulate import tabulate
    rows = [[a['asset_no'], a['name'], a['category'], a['department'] or '-',
             a['status'], a['user_name'] or '-']
            for a in target_assets]
    click.echo(tabulate(rows, headers=['资产编号', '名称', '类别', '部门', '状态', '使用人'],
                        tablefmt='simple'))

    if not mark_idle:
        click.echo("\n提示: 加上 --mark-idle 可将这些资产标记为闲置（会清空使用人）")
        return

    already_idle = sum(1 for a in target_assets if a['status'] == '闲置')
    to_idle = [a for a in target_assets if a['status'] != '闲置']

    if not to_idle:
        click.echo("\n所有资产已经是闲置状态，无需操作。")
        return

    if not yes:
        click.echo(f"\n将把 {len(to_idle)} 项资产标记为闲置（清空使用人）:")
        for a in to_idle[:10]:
            click.echo(f"  {a['asset_no']} - {a['name']} (原使用人: {a['user_name'] or '无'})")
        if len(to_idle) > 10:
            click.echo(f"  ... 还有 {len(to_idle) - 10} 项")
        if not click.confirm("确认标记为闲置?", default=True):
            click.echo("已取消")
            return

    with get_db() as conn:
        success = 0
        for asset in to_idle:
            old_status = asset['status']
            old_user = asset['user_name'] or '无'

            update_data = {'status': '闲置', 'user_name': ''}
            if remark:
                update_data['remark'] = (asset['remark'] + '; ' if asset['remark'] else '') + f'闲置原因: {remark}'

            update_asset(conn, asset['asset_no'], update_data)
            update_asset_timestamp(conn, asset['asset_no'])

            detail = f"从 {old_status} 标记为闲置，原使用人: {old_user}"
            if remark:
                detail += f" | 原因: {remark}"

            log_operation(conn, asset['asset_no'], '闲置', operator, detail)
            success += 1

    click.echo(f"\n操作完成: 成功标记 {success} 项为闲置")
