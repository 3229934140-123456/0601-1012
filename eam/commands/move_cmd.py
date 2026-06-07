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


@click.command('move')
@click.option('--asset-no', '-n', 'asset_nos', callback=_parse_asset_nos,
              help='资产编号，多个用逗号分隔')
@click.option('--department', '-d', help='按部门批量移动')
@click.option('--from-location', help='原存放地点（模糊匹配）')
@click.option('--to-location', '-l', required=True, help='新存放地点')
@click.option('--operator', default='system', help='操作人')
@click.option('--remark', help='备注')
@click.option('--yes', '-y', is_flag=True, help='跳过确认')
def move_cmd(asset_nos, department, from_location, to_location, operator, remark, yes):
    """变更资产存放地点"""
    with get_db() as conn:
        move_list = []

        if asset_nos:
            for no in asset_nos:
                asset = get_asset_by_no(conn, no)
                if asset:
                    move_list.append(asset)
                else:
                    click.echo(f"警告: 资产 {no} 不存在，跳过")
        elif department or from_location:
            filters = {}
            if department:
                filters['department'] = department
            if from_location:
                filters['location'] = from_location
            move_list = query_assets(conn, filters)
        else:
            click.echo("错误: 请指定资产编号、部门或原存放地点")
            return

        if not move_list:
            click.echo("没有可移动的资产")
            return

        if not yes:
            click.echo(f"将移动 {len(move_list)} 项资产到 '{to_location}':")
            for a in move_list[:5]:
                old_loc = a['location'] or '未设置'
                click.echo(f"  {a['asset_no']} - {a['name']} ({old_loc} -> {to_location})")
            if len(move_list) > 5:
                click.echo(f"  ... 还有 {len(move_list) - 5} 项")
            if not click.confirm("确认移动?", default=True):
                click.echo("已取消")
                return

        success = 0
        for asset in move_list:
            old_location = asset['location'] or '未设置'

            update_data = {'location': to_location}
            if remark:
                update_data['remark'] = (asset['remark'] + '; ' if asset['remark'] else '') + remark

            update_asset(conn, asset['asset_no'], update_data)
            update_asset_timestamp(conn, asset['asset_no'])

            detail = f"从 {old_location} 移动到 {to_location}"
            if remark:
                detail += f" | 备注: {remark}"

            log_operation(conn, asset['asset_no'], '移动', operator, detail)
            success += 1

    click.echo(f"\n移动完成: {success} 项资产")


@click.command('remark')
@click.argument('asset_no')
@click.argument('remark_text')
@click.option('--append/--replace', default=True, help='追加或替换备注')
@click.option('--operator', default='system', help='操作人')
def remark_cmd(asset_no, remark_text, append, operator):
    """追加或替换资产备注"""
    with get_db() as conn:
        asset = get_asset_by_no(conn, asset_no)
        if not asset:
            click.echo(f"错误: 资产 {asset_no} 不存在")
            return

        if append and asset['remark']:
            new_remark = asset['remark'] + '; ' + remark_text
        else:
            new_remark = remark_text

        update_asset(conn, asset_no, {'remark': new_remark})
        update_asset_timestamp(conn, asset_no)

        log_operation(
            conn,
            asset_no,
            '备注更新',
            operator,
            f"{'追加' if append else '替换'}备注: {remark_text}"
        )

    click.echo(f"资产 {asset_no} 备注已更新")
