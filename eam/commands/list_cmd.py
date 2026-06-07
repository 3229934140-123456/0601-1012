import csv
import click
from tabulate import tabulate
from ..database import get_db, query_assets, ASSET_CATEGORIES, ASSET_STATUS


def _format_assets(assets, columns=None):
    if not assets:
        return []

    default_columns = [
        ('asset_no', '资产编号'),
        ('name', '资产名称'),
        ('category', '类别'),
        ('brand', '品牌'),
        ('model', '型号'),
        ('department', '部门'),
        ('location', '存放地点'),
        ('user_name', '使用人'),
        ('status', '状态'),
        ('purchase_date', '购入日期'),
        ('purchase_price', '购入价格'),
    ]

    if columns:
        col_map = dict(default_columns)
        selected = [(c, col_map.get(c, c)) for c in columns if c in col_map]
    else:
        selected = default_columns

    rows = []
    for asset in assets:
        row = []
        for key, _ in selected:
            val = asset[key]
            if key == 'purchase_price':
                val = f"{val:.2f}" if val else ''
            row.append(val if val is not None else '')
        rows.append(row)

    headers = [h for _, h in selected]
    return headers, rows


@click.command('list')
@click.option('--asset-no', '-n', help='按资产编号筛选（模糊匹配）')
@click.option('--name', help='按资产名称筛选（模糊匹配）')
@click.option('--category', '-c', type=click.Choice(ASSET_CATEGORIES), help='按类别筛选')
@click.option('--department', '-d', help='按部门筛选')
@click.option('--status', '-s', type=click.Choice(ASSET_STATUS), help='按状态筛选')
@click.option('--user', '-u', 'user_name', help='按使用人筛选')
@click.option('--location', '-l', help='按存放地点筛选（模糊匹配）')
@click.option('--date-from', help='购入日期起始 (YYYY-MM-DD)')
@click.option('--date-to', help='购入日期截止 (YYYY-MM-DD)')
@click.option('--columns', help='显示列，逗号分隔')
@click.option('--export', '-e', help='导出到 CSV 文件')
@click.option('--limit', type=int, help='显示前 N 条')
@click.option('--count', is_flag=True, help='仅显示数量')
def list_cmd(asset_no, name, category, department, status, user_name,
              location, date_from, date_to, columns, export, limit, count):
    """查询资产列表"""
    filters = {}
    if asset_no:
        filters['asset_no'] = asset_no
    if name:
        filters['name'] = name
    if category:
        filters['category'] = category
    if department:
        filters['department'] = department
    if status:
        filters['status'] = status
    if user_name:
        filters['user_name'] = user_name
    if location:
        filters['location'] = location
    if date_from:
        filters['date_from'] = date_from
    if date_to:
        filters['date_to'] = date_to

    col_list = columns.split(',') if columns else None

    with get_db() as conn:
        assets = query_assets(conn, filters)

    if count:
        click.echo(f"共 {len(assets)} 条资产")
        return

    if limit and limit > 0:
        assets = assets[:limit]

    if not assets:
        click.echo("没有找到匹配的资产")
        return

    headers, rows = _format_assets(assets, col_list)

    click.echo(tabulate(rows, headers=headers, tablefmt='simple'))
    click.echo(f"\n共 {len(assets)} 条资产")

    if export:
        with open(export, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        click.echo(f"已导出到 {export}")


@click.command('view')
@click.argument('asset_no')
def view_cmd(asset_no):
    """查看单个资产详情"""
    from ..database import get_asset_by_no, get_operation_logs

    with get_db() as conn:
        asset = get_asset_by_no(conn, asset_no)
        if not asset:
            click.echo(f"未找到资产: {asset_no}")
            return

        logs = get_operation_logs(conn, {'asset_no': asset_no})

    click.echo("=" * 60)
    click.echo("  资产详情")
    click.echo("=" * 60)

    fields = [
        ('资产编号', 'asset_no'),
        ('资产名称', 'name'),
        ('类别', 'category'),
        ('品牌', 'brand'),
        ('型号', 'model'),
        ('序列号', 'serial_no'),
        ('购入日期', 'purchase_date'),
        ('购入价格', 'purchase_price'),
        ('所属部门', 'department'),
        ('存放地点', 'location'),
        ('使用人', 'user_name'),
        ('状态', 'status'),
        ('折旧状态', 'depreciation_status'),
        ('备注', 'remark'),
        ('创建时间', 'created_at'),
        ('更新时间', 'updated_at'),
    ]

    for label, key in fields:
        val = asset[key]
        if key == 'purchase_price' and val:
            val = f"{val:.2f} 元"
        click.echo(f"  {label}: {val if val else '-'}")

    click.echo("")
    click.echo("-" * 60)
    click.echo("  操作历史")
    click.echo("-" * 60)

    if not logs:
        click.echo("  暂无操作记录")
    else:
        for log in logs[:20]:
            click.echo(f"  [{log['created_at']}] {log['operation']} - {log['operator'] or '系统'}")
            if log['detail']:
                click.echo(f"    {log['detail']}")
