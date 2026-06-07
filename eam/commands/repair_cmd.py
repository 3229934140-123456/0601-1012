import click
from ..database import (
    get_db, get_asset_by_no, update_asset, log_operation,
    update_asset_timestamp, get_operation_logs
)


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
def repair_complete_cmd(asset_no, cost, result, operator, remark):
    """完成维修"""
    with get_db() as conn:
        asset = get_asset_by_no(conn, asset_no)
        if not asset:
            click.echo(f"错误: 资产 {asset_no} 不存在")
            return

        if asset['status'] != '维修中':
            click.echo(f"警告: 资产 {asset_no} 当前状态为 {asset['status']}，不在维修中")

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
@click.option('--date-from', help='开始日期 (YYYY-MM-DD)')
@click.option('--date-to', help='结束日期 (YYYY-MM-DD)')
@click.option('--export', '-e', help='导出到 CSV 文件')
def repair_list_cmd(status, date_from, date_to, export):
    """查看维修记录"""
    import csv
    from tabulate import tabulate

    with get_db() as conn:
        if status == '全部':
            operations = ['维修发起', '维修完成']
        elif status == '维修中':
            operations = ['维修发起']
        else:
            operations = ['维修完成']

        filters = {}
        if date_from:
            filters['date_from'] = date_from
        if date_to:
            filters['date_to'] = date_to

        all_logs = []
        for op in operations:
            filters['operation'] = op
            logs = get_operation_logs(conn, filters)
            all_logs.extend(logs)

        all_logs.sort(key=lambda x: x['created_at'], reverse=True)

    if not all_logs:
        click.echo("没有维修记录")
        return

    rows = []
    for log in all_logs:
        rows.append([
            log['created_at'],
            log['asset_no'],
            log['operation'],
            log['operator'] or '',
            log['detail'] or ''
        ])

    headers = ['时间', '资产编号', '操作', '操作人', '详情']
    click.echo(tabulate(rows, headers=headers, tablefmt='simple'))
    click.echo(f"\n共 {len(all_logs)} 条记录")

    if export:
        with open(export, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        click.echo(f"已导出到 {export}")


@click.command('repair-cost')
@click.option('--date-from', help='开始日期 (YYYY-MM-DD)')
@click.option('--date-to', help='结束日期 (YYYY-MM-DD)')
@click.option('--by-asset', is_flag=True, help='按资产统计')
@click.option('--by-month', is_flag=True, help='按月份统计')
def repair_cost_cmd(date_from, date_to, by_asset, by_month):
    """统计维修费用"""
    import re
    from tabulate import tabulate

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

    cost_pattern = re.compile(r'费用[:：]\s*([\d.]+)')

    for log in logs:
        match = cost_pattern.search(log['detail'] or '')
        if match:
            cost = float(match.group(1))
            total_cost += cost

            if by_asset:
                asset_costs[log['asset_no']] = asset_costs.get(log['asset_no'], 0) + cost

            if by_month:
                month = log['created_at'][:7]
                month_costs[month] = month_costs.get(month, 0) + cost

    click.echo(f"维修总费用: {total_cost:.2f} 元")
    click.echo(f"维修次数: {len(logs)} 次")

    if by_asset and asset_costs:
        click.echo("\n按资产统计:")
        rows = [[k, f"{v:.2f}"] for k, v in sorted(asset_costs.items(), key=lambda x: -x[1])]
        click.echo(tabulate(rows, headers=['资产编号', '费用(元)'], tablefmt='simple'))

    if by_month and month_costs:
        click.echo("\n按月份统计:")
        rows = [[k, f"{v:.2f}"] for k, v in sorted(month_costs.items())]
        click.echo(tabulate(rows, headers=['月份', '费用(元)'], tablefmt='simple'))
