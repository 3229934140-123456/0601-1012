import re
import csv
import os
from datetime import datetime, timedelta
import click
from tabulate import tabulate
from ..database import (
    get_db, get_asset_by_no, update_asset, log_operation,
    update_asset_timestamp, get_operation_logs, query_assets
)


def _parse_cost(detail):
    """从详情文本中提取费用"""
    if not detail:
        return 0
    match = re.search(r'费用[:：]\s*([\d.]+)', detail)
    if match:
        return float(match.group(1))
    return 0


def _build_repair_records(conn, filters=None):
    """
    构建维修记录，将维修发起和维修完成配对
    返回列表，每项是一个 dict 包含:
    asset_no, start_time, end_time, duration_days, cost, status, vendor, description, result
    """
    if filters is None:
        filters = {}

    start_logs = get_operation_logs(conn, {**filters, 'operation': '维修发起'})
    end_logs = get_operation_logs(conn, {**filters, 'operation': '维修完成'})

    end_by_asset = {}
    for log in end_logs:
        if log['asset_no'] not in end_by_asset:
            end_by_asset[log['asset_no']] = []
        end_by_asset[log['asset_no']].append(log)

    for no in end_by_asset:
        end_by_asset[no].sort(key=lambda x: x['created_at'])

    start_by_asset = {}
    for log in start_logs:
        if log['asset_no'] not in start_by_asset:
            start_by_asset[log['asset_no']] = []
        start_by_asset[log['asset_no']].append(log)

    for no in start_by_asset:
        start_by_asset[no].sort(key=lambda x: x['created_at'])

    repair_records = []

    all_asset_nos = set(start_by_asset.keys()) | set(end_by_asset.keys())

    for asset_no in sorted(all_asset_nos):
        starts = start_by_asset.get(asset_no, [])
        ends = end_by_asset.get(asset_no, [])

        end_idx = 0
        for start in starts:
            record = {
                'asset_no': asset_no,
                'start_time': start['created_at'],
                'end_time': None,
                'duration_days': None,
                'cost': 0,
                'status': '维修中',
                'vendor': '',
                'description': '',
                'result': '',
                'start_operator': start['operator'] or '',
                'end_operator': '',
            }

            detail = start['detail'] or ''
            desc_match = re.search(r'故障[:：]\s*(.+?)(?:\s*\||$)', detail)
            if desc_match:
                record['description'] = desc_match.group(1).strip()
            vendor_match = re.search(r'厂商[:：]\s*(.+?)(?:\s*\||$)', detail)
            if vendor_match:
                record['vendor'] = vendor_match.group(1).strip()
            start_cost = _parse_cost(detail)
            if start_cost:
                record['cost'] += start_cost

            while end_idx < len(ends):
                end_log = ends[end_idx]
                if end_log['created_at'] >= start['created_at']:
                    record['end_time'] = end_log['created_at']
                    record['status'] = '已完成'
                    record['end_operator'] = end_log['operator'] or ''

                    end_detail = end_log['detail'] or ''
                    result_match = re.search(r'结果[:：]\s*(.+?)(?:\s*\||$)', end_detail)
                    if result_match:
                        record['result'] = result_match.group(1).strip()
                    end_cost = _parse_cost(end_detail)
                    if end_cost:
                        record['cost'] += end_cost

                    try:
                        start_dt = datetime.strptime(start['created_at'], '%Y-%m-%d %H:%M:%S')
                        end_dt = datetime.strptime(end_log['created_at'], '%Y-%m-%d %H:%M:%S')
                        record['duration_days'] = (end_dt - start_dt).days
                    except (ValueError, TypeError):
                        record['duration_days'] = None

                    end_idx += 1
                    break
                end_idx += 1

            repair_records.append(record)

    return repair_records


@click.command('repair')
@click.argument('asset_no')
@click.option('--cost', type=float, help='维修费用')
@click.option('--vendor', help='维修厂商')
@click.option('--description', help='故障描述')
@click.option('--operator', default='system', help='操作人')
@click.option('--remark', help='备注')
def repair_start_cmd(asset_no, cost, vendor, description, operator, remark):
    """发起维修"""
    with get_db() as conn:
        asset = get_asset_by_no(conn, asset_no)
        if not asset:
            click.echo(f"错误: 资产 {asset_no} 不存在")
            return

        if asset['status'] == '维修中':
            click.echo(f"警告: 资产 {asset_no} 已在维修中")

        update_data = {'status': '维修中'}
        update_asset(conn, asset_no, update_data)
        update_asset_timestamp(conn, asset_no)

        details = []
        if description:
            details.append(f"故障: {description}")
        if vendor:
            details.append(f"厂商: {vendor}")
        if cost:
            details.append(f"费用: {cost:.2f} 元")
        if remark:
            details.append(f"备注: {remark}")

        log_operation(
            conn,
            asset_no,
            '维修发起',
            operator,
            ' | '.join(details) if details else '发起维修'
        )

    click.echo(f"资产 {asset_no} 已标记为维修中")


@click.command('repair-complete')
@click.argument('asset_no')
@click.option('--cost', type=float, help='实际维修费用')
@click.option('--result', help='维修结果')
@click.option('--operator', default='system', help='操作人')
@click.option('--remark', help='备注')
@click.option('--yes', '-y', is_flag=True, help='跳过确认')
def repair_complete_cmd(asset_no, cost, result, operator, remark, yes):
    """完成维修"""
    with get_db() as conn:
        asset = get_asset_by_no(conn, asset_no)
        if not asset:
            click.echo(f"错误: 资产 {asset_no} 不存在")
            return

        if asset['status'] != '维修中':
            click.echo(f"警告: 资产 {asset_no} 当前状态为 {asset['status']}，不在维修中")
            if not yes and not click.confirm("是否继续标记为维修完成?", default=False):
                click.echo("已取消")
                return

        new_status = '闲置'
        if asset['user_name']:
            new_status = '在用'

        update_data = {'status': new_status}
        update_asset(conn, asset_no, update_data)
        update_asset_timestamp(conn, asset_no)

        details = []
        if cost:
            details.append(f"费用: {cost:.2f} 元")
        if result:
            details.append(f"结果: {result}")
        if remark:
            details.append(f"备注: {remark}")

        log_operation(
            conn,
            asset_no,
            '维修完成',
            operator,
            ' | '.join(details) if details else '维修完成'
        )

    click.echo(f"资产 {asset_no} 维修完成，状态: {new_status}")


@click.command('repair-list')
@click.option('--status', type=click.Choice(['维修中', '已完成', '全部']), default='维修中',
              help='筛选维修状态')
@click.option('--asset-no', '-n', help='按资产编号筛选')
@click.option('--date-from', help='开始日期 (YYYY-MM-DD)')
@click.option('--date-to', help='结束日期 (YYYY-MM-DD)')
@click.option('--export', '-e', help='导出到文件 (CSV)')
@click.option('--format', '-f', 'fmt', type=click.Choice(['simple', 'detailed']),
              default='simple', help='显示格式')
def repair_list_cmd(status, asset_no, date_from, date_to, export, fmt):
    """查看维修记录（按次统计，含维修周期和费用）"""
    with get_db() as conn:
        filters = {}
        if date_from:
            filters['date_from'] = date_from
        if date_to:
            filters['date_to'] = date_to

        all_records = _build_repair_records(conn, filters)

    if status == '维修中':
        all_records = [r for r in all_records if r['status'] == '维修中']
    elif status == '已完成':
        all_records = [r for r in all_records if r['status'] == '已完成']

    if asset_no:
        all_records = [r for r in all_records if asset_no in r['asset_no']]

    all_records.sort(key=lambda x: x['start_time'], reverse=True)

    if not all_records:
        click.echo("没有维修记录")
        return

    if fmt == 'detailed':
        rows = []
        for r in all_records:
            duration = f"{r['duration_days']}天" if r['duration_days'] is not None else '进行中'
            cost_str = f"{r['cost']:.2f}" if r['cost'] else '-'
            rows.append([
                r['asset_no'],
                r['status'],
                r['start_time'],
                r['end_time'] or '-',
                duration,
                cost_str,
                r['vendor'] or '-',
                r['description'] or '-',
                r['result'] or '-',
            ])
        headers = ['资产编号', '状态', '开始时间', '完成时间', '维修周期', '费用(元)', '厂商', '故障', '结果']
    else:
        rows = []
        for r in all_records:
            duration = f"{r['duration_days']}天" if r['duration_days'] is not None else '进行中'
            cost_str = f"{r['cost']:.2f}" if r['cost'] else '-'
            rows.append([
                r['start_time'],
                r['asset_no'],
                r['status'],
                duration,
                cost_str,
                r['description'] or '-',
            ])
        headers = ['开始时间', '资产编号', '状态', '维修周期', '费用(元)', '故障描述']

    click.echo(tabulate(rows, headers=headers, tablefmt='simple'))
    click.echo(f"\n共 {len(all_records)} 次维修记录")

    in_progress = sum(1 for r in all_records if r['status'] == '维修中')
    completed = sum(1 for r in all_records if r['status'] == '已完成')
    total_cost = sum(r['cost'] for r in all_records)
    click.echo(f"维修中: {in_progress} 次，已完成: {completed} 次，总费用: {total_cost:.2f} 元")

    if export:
        with open(export, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
            writer.writerow([])
            writer.writerow(['统计'])
            writer.writerow(['总次数', len(all_records)])
            writer.writerow(['维修中', in_progress])
            writer.writerow(['已完成', completed])
            writer.writerow(['总费用(元)', f"{total_cost:.2f}"])
        click.echo(f"已导出到 {export}")


@click.command('repair-summary')
@click.option('--date-from', help='开始日期 (YYYY-MM-DD)')
@click.option('--date-to', help='结束日期 (YYYY-MM-DD)')
@click.option('--by-asset', is_flag=True, help='按资产统计')
@click.option('--by-month', is_flag=True, help='按月份统计')
@click.option('--export', '-e', help='导出到文件')
def repair_summary_cmd(date_from, date_to, by_asset, by_month, export):
    """维修费用和周期统计"""
    with get_db() as conn:
        filters = {}
        if date_from:
            filters['date_from'] = date_from
        if date_to:
            filters['date_to'] = date_to

        records = _build_repair_records(conn, filters)

    completed = [r for r in records if r['status'] == '已完成']
    in_progress = [r for r in records if r['status'] == '维修中']

    total_cost = sum(r['cost'] for r in records)
    total_durations = [r['duration_days'] for r in completed if r['duration_days'] is not None]
    avg_duration = sum(total_durations) / len(total_durations) if total_durations else 0

    click.echo("=" * 50)
    click.echo("  维修统计")
    click.echo("=" * 50)
    click.echo(f"  维修总次数: {len(records)}")
    click.echo(f"  已完成: {len(completed)} 次")
    click.echo(f"  维修中: {len(in_progress)} 次")
    click.echo(f"  总费用: {total_cost:.2f} 元")
    click.echo(f"  平均维修周期: {avg_duration:.1f} 天")
    click.echo("=" * 50)

    if by_asset:
        asset_stats = {}
        for r in records:
            no = r['asset_no']
            if no not in asset_stats:
                asset_stats[no] = {'count': 0, 'total_cost': 0, 'total_days': 0, 'days_count': 0}
            asset_stats[no]['count'] += 1
            asset_stats[no]['total_cost'] += r['cost']
            if r['duration_days'] is not None:
                asset_stats[no]['total_days'] += r['duration_days']
                asset_stats[no]['days_count'] += 1

        click.echo("\n按资产统计:")
        rows = []
        for no, s in sorted(asset_stats.items(), key=lambda x: -x[1]['total_cost']):
            avg_d = s['total_days'] / s['days_count'] if s['days_count'] else 0
            rows.append([no, s['count'], f"{s['total_cost']:.2f}", f"{avg_d:.1f}"])
        click.echo(tabulate(rows, headers=['资产编号', '维修次数', '总费用(元)', '平均周期(天)'],
                            tablefmt='simple'))

    if by_month:
        month_stats = {}
        for r in records:
            month = r['start_time'][:7]
            if month not in month_stats:
                month_stats[month] = {'count': 0, 'total_cost': 0, 'completed': 0}
            month_stats[month]['count'] += 1
            month_stats[month]['total_cost'] += r['cost']
            if r['status'] == '已完成':
                month_stats[month]['completed'] += 1

        click.echo("\n按月份统计:")
        rows = []
        for month in sorted(month_stats.keys()):
            s = month_stats[month]
            rows.append([month, s['count'], s['completed'], f"{s['total_cost']:.2f}"])
        click.echo(tabulate(rows, headers=['月份', '发起数', '完成数', '费用(元)'],
                            tablefmt='simple'))

    if export:
        with open(export, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['指标', '数值'])
            writer.writerow(['维修总次数', len(records)])
            writer.writerow(['已完成', len(completed)])
            writer.writerow(['维修中', len(in_progress)])
            writer.writerow(['总费用(元)', f"{total_cost:.2f}"])
            writer.writerow(['平均维修周期(天)', f"{avg_duration:.1f}"])
            writer.writerow([])

            if by_asset:
                writer.writerow(['按资产统计'])
                writer.writerow(['资产编号', '维修次数', '总费用(元)', '平均周期(天)'])
                for no, s in sorted(asset_stats.items(), key=lambda x: -x[1]['total_cost']):
                    avg_d = s['total_days'] / s['days_count'] if s['days_count'] else 0
                    writer.writerow([no, s['count'], f"{s['total_cost']:.2f}", f"{avg_d:.1f}"])
                writer.writerow([])

            if by_month:
                writer.writerow(['按月份统计'])
                writer.writerow(['月份', '发起数', '完成数', '费用(元)'])
                for month in sorted(month_stats.keys()):
                    s = month_stats[month]
                    writer.writerow([month, s['count'], s['completed'], f"{s['total_cost']:.2f}"])
        click.echo(f"\n已导出到 {export}")


@click.command('repair-cost')
@click.option('--date-from', help='开始日期 (YYYY-MM-DD)')
@click.option('--date-to', help='结束日期 (YYYY-MM-DD)')
@click.option('--by-asset', is_flag=True, help='按资产统计')
@click.option('--by-month', is_flag=True, help='按月份统计')
def repair_cost_cmd(date_from, date_to, by_asset, by_month):
    """统计维修费用（保留原命令，兼容旧用法）"""
    with get_db() as conn:
        filters = {'operation': '维修完成'}
        if date_from:
            filters['date_from'] = date_from
        if date_to:
            filters['date_to'] = date_to

        logs = get_operation_logs(conn, filters)

    total_cost = 0
    asset_costs = {}
    month_costs = {}

    for log in logs:
        cost = _parse_cost(log['detail'] or '')
        if cost:
            total_cost += cost

            if by_asset:
                asset_costs[log['asset_no']] = asset_costs.get(log['asset_no'], 0) + cost

            if by_month:
                month = log['created_at'][:7]
                month_costs[month] = month_costs.get(month, 0) + cost

    click.echo(f"维修总费用: {total_cost:.2f} 元")
    click.echo(f"维修完成次数: {len(logs)} 次")

    if by_asset and asset_costs:
        click.echo("\n按资产统计:")
        rows = [[k, f"{v:.2f}"] for k, v in sorted(asset_costs.items(), key=lambda x: -x[1])]
        click.echo(tabulate(rows, headers=['资产编号', '费用(元)'], tablefmt='simple'))

    if by_month and month_costs:
        click.echo("\n按月份统计:")
        rows = [[k, f"{v:.2f}"] for k, v in sorted(month_costs.items())]
        click.echo(tabulate(rows, headers=['月份', '费用(元)'], tablefmt='simple'))


def _build_repair_ledger(conn, filters=None):
    """
    构建维修台账（按资产维度汇总）
    返回列表，每项包含资产信息和维修统计
    """
    if filters is None:
        filters = {}

    log_filters = {}
    if filters.get('date_from'):
        log_filters['date_from'] = filters['date_from']
    if filters.get('date_to'):
        log_filters['date_to'] = filters['date_to']

    all_records = _build_repair_records(conn, log_filters)

    asset_filters = {}
    if filters.get('department'):
        asset_filters['department'] = filters['department']
    if filters.get('category'):
        asset_filters['category'] = filters['category']
    if filters.get('status'):
        asset_filters['status'] = filters['status']

    if asset_filters:
        assets = query_assets(conn, asset_filters)
        asset_nos = {a['asset_no'] for a in assets}
        all_records = [r for r in all_records if r['asset_no'] in asset_nos]

    asset_stats = {}
    for r in all_records:
        no = r['asset_no']
        if no not in asset_stats:
            asset_stats[no] = {
                'count': 0,
                'total_cost': 0,
                'total_days': 0,
                'days_count': 0,
                'last_start': None,
                'last_end': None,
                'last_cost': 0,
                'current_status': '无维修记录',
                'records': [],
            }
        s = asset_stats[no]
        s['count'] += 1
        s['total_cost'] += r['cost']
        s['records'].append(r)

        if r['duration_days'] is not None:
            s['total_days'] += r['duration_days']
            s['days_count'] += 1

    for no, s in asset_stats.items():
        s['records'].sort(key=lambda x: x['start_time'], reverse=True)
        latest = s['records'][0]
        s['last_start'] = latest['start_time']
        s['last_end'] = latest['end_time']
        s['last_cost'] = latest['cost']
        s['current_status'] = latest['status']

    all_asset_nos = set()
    if asset_filters:
        assets = query_assets(conn, asset_filters)
        all_asset_nos = {a['asset_no']: a for a in assets}
    else:
        assets = query_assets(conn, {})
        all_asset_nos = {a['asset_no']: a for a in assets}

    ledger = []
    for no in sorted(all_asset_nos.keys()):
        asset = all_asset_nos[no]
        if no in asset_stats:
            s = asset_stats[no]
            avg_days = s['total_days'] / s['days_count'] if s['days_count'] else 0
            ledger.append({
                'asset_no': no,
                'name': asset['name'],
                'category': asset['category'],
                'department': asset['department'] or '',
                'current_status': s['current_status'],
                'repair_count': s['count'],
                'total_cost': s['total_cost'],
                'last_start': s['last_start'],
                'last_end': s['last_end'] or '',
                'last_cost': s['last_cost'],
                'avg_days': avg_days,
            })
        elif filters.get('show_all'):
            ledger.append({
                'asset_no': no,
                'name': asset['name'],
                'category': asset['category'],
                'department': asset['department'] or '',
                'current_status': asset['status'],
                'repair_count': 0,
                'total_cost': 0,
                'last_start': '',
                'last_end': '',
                'last_cost': 0,
                'avg_days': 0,
            })

    return ledger


@click.command('repair-ledger')
@click.option('--department', '-d', help='按部门筛选')
@click.option('--category', '-c', help='按类别筛选')
@click.option('--status', help='按资产当前状态筛选')
@click.option('--date-from', help='维修开始日期 (YYYY-MM-DD)')
@click.option('--date-to', help='维修结束日期 (YYYY-MM-DD)')
@click.option('--show-all', is_flag=True, help='显示所有资产（含无维修记录的）')
@click.option('--export', '-e', help='导出到文件 (CSV/Excel)')
@click.option('--format', '-f', 'fmt', type=click.Choice(['simple', 'detailed']),
              default='simple', help='显示格式')
def repair_ledger_cmd(department, category, status, date_from, date_to, show_all, export, fmt):
    """维修台账（按资产汇总，含最近维修信息和历史统计）"""
    with get_db() as conn:
        filters = {}
        if department:
            filters['department'] = department
        if category:
            filters['category'] = category
        if status:
            filters['status'] = status
        if date_from:
            filters['date_from'] = date_from
        if date_to:
            filters['date_to'] = date_to
        if show_all:
            filters['show_all'] = True

        ledger = _build_repair_ledger(conn, filters)

    if not ledger:
        click.echo("没有符合条件的资产")
        return

    if fmt == 'detailed':
        headers = ['资产编号', '资产名称', '类别', '部门', '当前状态',
                   '维修次数', '总费用(元)', '最近开始', '最近完成', '最近费用', '平均周期(天)']
        rows = []
        for item in ledger:
            rows.append([
                item['asset_no'],
                item['name'],
                item['category'],
                item['department'] or '-',
                item['current_status'],
                item['repair_count'],
                f"{item['total_cost']:.2f}",
                item['last_start'] or '-',
                item['last_end'] or '-',
                f"{item['last_cost']:.2f}" if item['last_cost'] else '-',
                f"{item['avg_days']:.1f}" if item['avg_days'] else '-',
            ])
    else:
        headers = ['资产编号', '资产名称', '部门', '当前状态', '维修次数', '总费用(元)', '最近开始']
        rows = []
        for item in ledger:
            rows.append([
                item['asset_no'],
                item['name'],
                item['department'] or '-',
                item['current_status'],
                item['repair_count'],
                f"{item['total_cost']:.2f}",
                item['last_start'] or '-',
            ])

    click.echo("=" * 80)
    click.echo("  维修台账")
    dept_str = f" | 部门: {department}" if department else ""
    cat_str = f" | 类别: {category}" if category else ""
    date_str = ""
    if date_from or date_to:
        date_str = f" | 区间: {date_from or '开始'} ~ {date_to or '至今'}"
    click.echo(f"  共 {len(ledger)} 项资产{dept_str}{cat_str}{date_str}")
    click.echo("=" * 80)
    click.echo(tabulate(rows, headers=headers, tablefmt='simple'))

    total_count = sum(item['repair_count'] for item in ledger)
    total_cost = sum(item['total_cost'] for item in ledger)
    has_repair = sum(1 for item in ledger if item['repair_count'] > 0)
    click.echo(f"\n有维修记录: {has_repair} 项，总维修次数: {total_count} 次，总费用: {total_cost:.2f} 元")

    if export:
        ext = os.path.splitext(export)[1].lower()
        if ext == '.csv':
            with open(export, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['资产编号', '资产名称', '类别', '部门', '当前状态',
                                 '维修次数', '总费用(元)', '最近开始时间', '最近完成时间',
                                 '最近费用(元)', '平均维修周期(天)'])
                for item in ledger:
                    writer.writerow([
                        item['asset_no'], item['name'], item['category'],
                        item['department'], item['current_status'],
                        item['repair_count'], f"{item['total_cost']:.2f}",
                        item['last_start'], item['last_end'],
                        f"{item['last_cost']:.2f}" if item['last_cost'] else '',
                        f"{item['avg_days']:.1f}" if item['avg_days'] else '',
                    ])
            click.echo(f"\n已导出到 {export}")
        elif ext in ['.xlsx', '.xls']:
            try:
                from openpyxl import Workbook
                wb = Workbook()
                ws = wb.active
                ws.title = '维修台账'
                ws.append(['资产编号', '资产名称', '类别', '部门', '当前状态',
                           '维修次数', '总费用(元)', '最近开始时间', '最近完成时间',
                           '最近费用(元)', '平均维修周期(天)'])
                for item in ledger:
                    ws.append([
                        item['asset_no'], item['name'], item['category'],
                        item['department'], item['current_status'],
                        item['repair_count'], item['total_cost'],
                        item['last_start'], item['last_end'],
                        item['last_cost'], item['avg_days'],
                    ])
                wb.save(export)
                click.echo(f"\n已导出到 {export}")
            except ImportError:
                click.echo("\n错误: 需要安装 openpyxl 才能导出 Excel 文件")
        else:
            click.echo(f"\n错误: 不支持的导出格式 {ext}")
