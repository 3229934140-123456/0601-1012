import os
import csv
import re
from datetime import datetime, timedelta
import click
from tabulate import tabulate
from ..database import get_db


@click.command('audit')
@click.option('--repair-days', type=int, default=30, help='维修超期天数阈值（默认30天）')
@click.option('--idle-days', type=int, default=90, help='长期闲置天数阈值（默认90天）')
@click.option('--type', '-t', 'audit_types',
              type=click.Choice(['overdue-repair', 'long-idle', 'dirty-data', 'all']),
              multiple=True, help='审计类型，可多选')
@click.option('--department', '-d', help='按部门筛选')
@click.option('--category', '-c', help='按类别筛选')
@click.option('--export', '-e', help='导出到文件 (CSV/Excel)')
@click.option('--format', '-f', 'fmt', type=click.Choice(['csv', 'xlsx']),
              default='csv', help='导出格式')
def audit_cmd(repair_days, idle_days, audit_types, department, category, export, fmt):
    """审计异常资产（超期维修、长期闲置、脏数据等）"""
    if not audit_types:
        audit_types = ['all']

    do_all = 'all' in audit_types

    with get_db() as conn:
        results = {}

        if do_all or 'overdue-repair' in audit_types:
            results['overdue_repair'] = _audit_overdue_repair(conn, repair_days, department, category)

        if do_all or 'long-idle' in audit_types:
            results['long_idle'] = _audit_long_idle(conn, idle_days, department, category)

        if do_all or 'dirty-data' in audit_types:
            results['dirty_data'] = _audit_dirty_data(conn, department, category)

    total = sum(len(v) for v in results.values())

    click.echo("=" * 80)
    click.echo("  资产审计报告")
    click.echo("=" * 80)
    click.echo(f"  阈值: 维修超期 > {repair_days} 天，长期闲置 > {idle_days} 天")
    if department:
        click.echo(f"  部门: {department}")
    if category:
        click.echo(f"  类别: {category}")
    click.echo(f"  共发现 {total} 项异常")
    click.echo("=" * 80)
    click.echo()

    if 'overdue_repair' in results:
        _print_overdue_repair(results['overdue_repair'])

    if 'long_idle' in results:
        _print_long_idle(results['long_idle'])

    if 'dirty_data' in results:
        _print_dirty_data(results['dirty_data'])

    if export:
        _export_audit_results(export, fmt, results, repair_days, idle_days, department, category)
        click.echo(f"\n审计报告已导出到: {export}")


def _audit_overdue_repair(conn, days, department, category):
    """审计超期维修中的资产"""
    cursor = conn.cursor()
    threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

    query = '''
        SELECT a.asset_no, a.name, a.category, a.department, a.status,
               ol.created_at as repair_start, ol.detail as repair_detail
        FROM assets a
        JOIN operation_logs ol ON a.asset_no = ol.asset_no
        WHERE a.status = '维修中'
          AND ol.operation = '维修发起'
          AND ol.created_at <= ?
          AND NOT EXISTS (
              SELECT 1 FROM operation_logs ol2
              WHERE ol2.asset_no = a.asset_no
                AND ol2.operation = '维修完成'
                AND ol2.created_at > ol.created_at
          )
    '''
    params = [threshold_date]

    if department:
        query += ' AND a.department = ?'
        params.append(department)
    if category:
        query += ' AND a.category = ?'
        params.append(category)

    query += ' ORDER BY ol.created_at ASC'

    cursor.execute(query, params)
    rows = cursor.fetchall()

    result = []
    for row in rows:
        start_str = row['repair_start']
        try:
            start_dt = datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S')
            repair_days_val = (datetime.now() - start_dt).days
        except (ValueError, TypeError):
            repair_days_val = 0

        detail = row['repair_detail'] or ''
        desc_match = re.search(r'故障[:：]\s*(.+?)(?:\s*\||$)', detail)
        description = desc_match.group(1).strip() if desc_match else ''

        result.append({
            'asset_no': row['asset_no'],
            'name': row['name'],
            'category': row['category'],
            'department': row['department'] or '',
            'status': row['status'],
            'repair_days': repair_days_val,
            'repair_start': start_str,
            'description': description,
        })

    return result


def _audit_long_idle(conn, days, department, category):
    """审计长期闲置的资产"""
    cursor = conn.cursor()
    threshold_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

    query = '''
        SELECT * FROM assets
        WHERE status = '闲置'
          AND updated_at <= ?
    '''
    params = [threshold_date]

    if department:
        query += ' AND department = ?'
        params.append(department)
    if category:
        query += ' AND category = ?'
        params.append(category)

    query += ' ORDER BY updated_at ASC'

    cursor.execute(query, params)
    rows = cursor.fetchall()

    result = []
    for row in rows:
        updated_str = row['updated_at']
        try:
            updated_dt = datetime.strptime(updated_str, '%Y-%m-%d %H:%M:%S')
            idle_days_val = (datetime.now() - updated_dt).days
        except (ValueError, TypeError):
            idle_days_val = 0

        result.append({
            'asset_no': row['asset_no'],
            'name': row['name'],
            'category': row['category'],
            'department': row['department'] or '',
            'idle_days': idle_days_val,
            'last_user': row['user_name'] or '',
            'last_change': updated_str,
        })

    return result


def _audit_dirty_data(conn, department, category):
    """审计脏数据"""
    cursor = conn.cursor()
    issues = []

    query1 = '''
        SELECT * FROM assets
        WHERE status = '已报废' AND user_name IS NOT NULL AND user_name != ''
    '''
    params = []
    if department:
        query1 += ' AND department = ?'
        params.append(department)
    if category:
        query1 += ' AND category = ?'
        params.append(category)

    cursor.execute(query1, params)
    for row in cursor.fetchall():
        issues.append({
            'asset_no': row['asset_no'],
            'name': row['name'],
            'category': row['category'],
            'department': row['department'] or '',
            'status': row['status'],
            'user_name': row['user_name'] or '',
            'issue': '已报废但仍有使用人',
        })

    query2 = '''
        SELECT * FROM assets
        WHERE status = '在用' AND (user_name IS NULL OR user_name = '')
    '''
    params2 = []
    if department:
        query2 += ' AND department = ?'
        params2.append(department)
    if category:
        query2 += ' AND category = ?'
        params2.append(category)

    cursor.execute(query2, params2)
    for row in cursor.fetchall():
        issues.append({
            'asset_no': row['asset_no'],
            'name': row['name'],
            'category': row['category'],
            'department': row['department'] or '',
            'status': row['status'],
            'user_name': row['user_name'] or '',
            'issue': '在用状态但无使用人',
        })

    issues.sort(key=lambda x: x['asset_no'])
    return issues


def _print_overdue_repair(items):
    click.echo(f"  ▶ 超期维修中资产（{len(items)} 项）")
    click.echo("  " + "-" * 76)
    if items:
        rows = []
        for item in items[:20]:
            rows.append([
                item['asset_no'], item['name'], item['department'],
                item['repair_days'], item['repair_start'],
                item['description'] or '-',
            ])
        click.echo(tabulate(rows,
                            headers=['资产编号', '资产名称', '部门', '维修天数', '开始时间', '故障描述'],
                            tablefmt='simple'))
        if len(items) > 20:
            click.echo(f"  ... 还有 {len(items) - 20} 条")
    else:
        click.echo("  （无异常）")
    click.echo()


def _print_long_idle(items):
    click.echo(f"  ▶ 长期闲置资产（{len(items)} 项）")
    click.echo("  " + "-" * 76)
    if items:
        rows = []
        for item in items[:20]:
            rows.append([
                item['asset_no'], item['name'], item['department'],
                item['idle_days'], item['last_user'] or '-',
                item['last_change'],
            ])
        click.echo(tabulate(rows,
                            headers=['资产编号', '资产名称', '部门', '闲置天数', '最后使用人', '最后变更时间'],
                            tablefmt='simple'))
        if len(items) > 20:
            click.echo(f"  ... 还有 {len(items) - 20} 条")
    else:
        click.echo("  （无异常）")
    click.echo()


def _print_dirty_data(items):
    click.echo(f"  ▶ 脏数据（{len(items)} 项）")
    click.echo("  " + "-" * 76)
    if items:
        rows = []
        for item in items[:20]:
            rows.append([
                item['asset_no'], item['name'], item['department'],
                item['status'], item['user_name'] or '-',
                item['issue'],
            ])
        click.echo(tabulate(rows,
                            headers=['资产编号', '资产名称', '部门', '状态', '使用人', '问题描述'],
                            tablefmt='simple'))
        if len(items) > 20:
            click.echo(f"  ... 还有 {len(items) - 20} 条")
    else:
        click.echo("  （无异常）")
    click.echo()


def _export_audit_results(filepath, fmt, results, repair_days, idle_days, department, category):
    """导出审计结果"""
    ext = os.path.splitext(filepath)[1].lower()

    if fmt == 'xlsx' or ext in ['.xlsx', '.xls']:
        try:
            from openpyxl import Workbook
            wb = Workbook()

            ws = wb.active
            ws.title = '汇总'
            ws.append(['资产审计报告'])
            ws.append(['生成时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
            ws.append(['维修超期阈值(天)', repair_days])
            ws.append(['长期闲置阈值(天)', idle_days])
            if department:
                ws.append(['部门', department])
            if category:
                ws.append(['类别', category])
            ws.append([])
            ws.append(['分类', '数量'])
            for section_name, items in [
                ('超期维修中资产', results.get('overdue_repair', [])),
                ('长期闲置资产', results.get('long_idle', [])),
                ('脏数据', results.get('dirty_data', [])),
            ]:
                ws.append([section_name, len(items)])

            if 'overdue_repair' in results:
                ws2 = wb.create_sheet('超期维修')
                ws2.append(['资产编号', '资产名称', '类别', '部门', '状态',
                            '维修天数', '开始时间', '故障描述'])
                for item in results['overdue_repair']:
                    ws2.append([
                        item['asset_no'], item['name'], item['category'],
                        item['department'], item['status'],
                        item['repair_days'], item['repair_start'],
                        item['description'],
                    ])

            if 'long_idle' in results:
                ws3 = wb.create_sheet('长期闲置')
                ws3.append(['资产编号', '资产名称', '类别', '部门',
                            '闲置天数', '最后使用人', '最后变更时间'])
                for item in results['long_idle']:
                    ws3.append([
                        item['asset_no'], item['name'], item['category'],
                        item['department'], item['idle_days'],
                        item['last_user'], item['last_change'],
                    ])

            if 'dirty_data' in results:
                ws4 = wb.create_sheet('脏数据')
                ws4.append(['资产编号', '资产名称', '类别', '部门',
                           '状态', '使用人', '问题描述'])
                for item in results['dirty_data']:
                    ws4.append([
                        item['asset_no'], item['name'], item['category'],
                        item['department'], item['status'],
                        item['user_name'], item['issue'],
                    ])

            wb.save(filepath)
        except ImportError:
            click.echo("错误: 需要安装 openpyxl 才能导出 Excel 文件")
    else:
        with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['资产审计报告'])
            writer.writerow(['生成时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
            writer.writerow(['维修超期阈值(天)', repair_days])
            writer.writerow(['长期闲置阈值(天)', idle_days])
            if department:
                writer.writerow(['部门', department])
            if category:
                writer.writerow(['类别', category])
            writer.writerow([])

            if 'overdue_repair' in results:
                items = results['overdue_repair']
                writer.writerow([f'=== 超期维修中资产 ({len(items)} 项) ==='])
                writer.writerow(['资产编号', '资产名称', '类别', '部门', '状态',
                                '维修天数', '开始时间', '故障描述'])
                for item in items:
                    writer.writerow([
                        item['asset_no'], item['name'], item['category'],
                        item['department'], item['status'],
                        item['repair_days'], item['repair_start'],
                        item['description'],
                    ])
                writer.writerow([])

            if 'long_idle' in results:
                items = results['long_idle']
                writer.writerow([f'=== 长期闲置资产 ({len(items)} 项) ==='])
                writer.writerow(['资产编号', '资产名称', '类别', '部门',
                                '闲置天数', '最后使用人', '最后变更时间'])
                for item in items:
                    writer.writerow([
                        item['asset_no'], item['name'], item['category'],
                        item['department'], item['idle_days'],
                        item['last_user'], item['last_change'],
                    ])
                writer.writerow([])

            if 'dirty_data' in results:
                items = results['dirty_data']
                writer.writerow([f'=== 脏数据 ({len(items)} 项) ==='])
                writer.writerow(['资产编号', '资产名称', '类别', '部门',
                               '状态', '使用人', '问题描述'])
                for item in items:
                    writer.writerow([
                        item['asset_no'], item['name'], item['category'],
                        item['department'], item['status'],
                        item['user_name'], item['issue'],
                    ])
                writer.writerow([])
