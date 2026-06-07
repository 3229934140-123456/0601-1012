import os
import csv
import click
from tabulate import tabulate
from ..database import (
    get_db, asset_exists, insert_asset, get_asset_by_no,
    log_operation, ASSET_CATEGORIES, ASSET_STATUS
)


def _read_csv(filepath):
    assets = []
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            asset = {k.strip(): v.strip() for k, v in row.items() if v is not None}
            assets.append(asset)
    return assets


def _read_excel(filepath):
    try:
        from openpyxl import load_workbook
    except ImportError:
        click.echo("错误: 需要安装 openpyxl 才能读取 Excel 文件。运行: pip install openpyxl")
        return []

    wb = load_workbook(filepath, data_only=True)
    ws = wb.active

    headers = []
    for cell in ws[1]:
        headers.append(cell.value)

    assets = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        asset = {}
        for i, value in enumerate(row):
            if i < len(headers) and headers[i]:
                key = str(headers[i]).strip()
                asset[key] = str(value).strip() if value is not None else ''
        if asset.get('asset_no') or asset.get('资产编号'):
            assets.append(asset)

    return assets


def _normalize_asset(raw):
    mapping = {
        '资产编号': 'asset_no',
        '资产名称': 'name',
        '名称': 'name',
        '类别': 'category',
        '资产类别': 'category',
        '品牌': 'brand',
        '型号': 'model',
        '序列号': 'serial_no',
        '序列号/ SN': 'serial_no',
        '购入日期': 'purchase_date',
        '购买日期': 'purchase_date',
        '购入价格': 'purchase_price',
        '购买价格': 'purchase_price',
        '价格': 'purchase_price',
        '所属部门': 'department',
        '部门': 'department',
        '存放地点': 'location',
        '地点': 'location',
        '使用人': 'user_name',
        '保管人': 'user_name',
        '状态': 'status',
        '折旧状态': 'depreciation_status',
        '备注': 'remark',
    }

    normalized = {}
    for k, v in raw.items():
        key = mapping.get(k, k)
        if key in ['asset_no', 'name', 'category', 'brand', 'model', 'serial_no',
                   'purchase_date', 'purchase_price', 'department', 'location',
                   'user_name', 'status', 'depreciation_status', 'remark']:
            normalized[key] = v

    if not normalized.get('asset_no'):
        return None

    if not normalized.get('name'):
        normalized['name'] = normalized['asset_no']

    if not normalized.get('category'):
        normalized['category'] = '办公设备'

    if not normalized.get('status'):
        normalized['status'] = '闲置'

    if normalized.get('purchase_price'):
        try:
            normalized['purchase_price'] = float(normalized['purchase_price'])
        except (ValueError, TypeError):
            normalized['purchase_price'] = 0
    else:
        normalized['purchase_price'] = 0

    return normalized


@click.command('import')
@click.argument('filepath', type=click.Path(exists=True))
@click.option('--dry-run', is_flag=True, help='仅校验不导入')
@click.option('--operator', default='system', help='操作人')
@click.option('--skip-duplicates', is_flag=True, help='跳过重复编号')
def import_cmd(filepath, dry_run, operator, skip_duplicates):
    """导入资产清单（支持 CSV 和 Excel）"""
    ext = os.path.splitext(filepath)[1].lower()

    if ext == '.csv':
        raw_assets = _read_csv(filepath)
    elif ext in ['.xlsx', '.xls']:
        raw_assets = _read_excel(filepath)
    else:
        click.echo(f"错误: 不支持的文件格式 {ext}")
        return

    if not raw_assets:
        click.echo("未读取到任何资产数据")
        return

    click.echo(f"读取到 {len(raw_assets)} 条数据，正在处理...")

    normalized_list = []
    invalid_list = []
    for i, raw in enumerate(raw_assets, 1):
        normalized = _normalize_asset(raw)
        if not normalized:
            invalid_list.append((i, '缺少资产编号', raw))
        else:
            normalized_list.append(normalized)

    if invalid_list:
        click.echo(f"\n警告: {len(invalid_list)} 条数据无效:")
        for idx, reason, raw in invalid_list[:5]:
            click.echo(f"  第 {idx} 行: {reason} - {raw}")
        if len(invalid_list) > 5:
            click.echo(f"  ... 还有 {len(invalid_list) - 5} 条")

    with get_db() as conn:
        duplicates = []
        new_assets = []

        for asset in normalized_list:
            if asset_exists(conn, asset['asset_no']):
                duplicates.append(asset['asset_no'])
            else:
                new_assets.append(asset)

        if duplicates:
            click.echo(f"\n发现 {len(duplicates)} 个重复编号:")
            for no in duplicates[:10]:
                click.echo(f"  {no}")
            if len(duplicates) > 10:
                click.echo(f"  ... 还有 {len(duplicates) - 10} 个")

        if dry_run:
            click.echo(f"\n[试运行] 将导入 {len(new_assets)} 条新资产，跳过 {len(duplicates)} 条重复")
            return

        imported = 0
        skipped = 0

        for asset in normalized_list:
            if asset_exists(conn, asset['asset_no']):
                if skip_duplicates:
                    skipped += 1
                    continue
                else:
                    click.echo(f"跳过重复编号: {asset['asset_no']}")
                    skipped += 1
                    continue

            insert_asset(conn, asset)
            log_operation(
                conn,
                asset['asset_no'],
                '导入',
                operator,
                f"导入资产: {asset.get('name', '')}"
            )
            imported += 1

    click.echo(f"\n导入完成: 成功 {imported} 条，跳过 {skipped} 条")


@click.command('check-duplicates')
@click.option('--output', '-o', help='导出重复清单到文件')
def check_duplicates_cmd(output):
    """检查重复编号"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT asset_no, COUNT(*) as cnt
            FROM assets
            GROUP BY asset_no
            HAVING cnt > 1
        ''')
        dupes = cursor.fetchall()

    if not dupes:
        click.echo("未发现重复编号")
        return

    click.echo(f"发现 {len(dupes)} 个重复编号:")
    table = [[row['asset_no'], row['cnt']] for row in dupes]
    click.echo(tabulate(table, headers=['资产编号', '出现次数'], tablefmt='simple'))

    if output:
        with open(output, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['资产编号', '出现次数'])
            writer.writerows(table)
        click.echo(f"\n重复清单已导出到: {output}")
