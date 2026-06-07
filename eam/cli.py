import click
from .database import init_db, get_db_path
from .commands.import_cmd import import_cmd, check_duplicates_cmd
from .commands.list_cmd import list_cmd, view_cmd
from .commands.assign_cmd import assign_cmd, return_cmd, transfer_cmd
from .commands.repair_cmd import (
    repair_start_cmd, repair_complete_cmd, repair_list_cmd, repair_cost_cmd,
    repair_summary_cmd
)
from .commands.batch_cmd import batch_cmd, batch_template_cmd
from .commands.move_cmd import move_cmd, remark_cmd
from .commands.tag_cmd import (
    tag_cmd, status_cmd, depreciation_cmd, scrap_cmd, idle_cmd
)
from .commands.report_cmd import (
    report_cmd, inventory_diff_cmd, history_cmd, export_cmd, monthly_report_cmd
)


@click.group()
@click.version_option(version='1.0.0', prog_name='eam')
@click.pass_context
def cli(ctx):
    """企业资产管理命令行工具 (EAM)

    用于批量管理电脑、工牌和办公设备等企业资产。
    """
    init_db()


@cli.command('init')
def init_cmd():
    """初始化数据库"""
    init_db()
    click.echo(f"数据库已初始化: {get_db_path()}")


@cli.command('db-path')
def db_path_cmd():
    """显示数据库文件路径"""
    click.echo(get_db_path())


cli.add_command(import_cmd, name='import')
cli.add_command(check_duplicates_cmd, name='check-duplicates')
cli.add_command(list_cmd, name='list')
cli.add_command(view_cmd, name='view')
cli.add_command(assign_cmd, name='assign')
cli.add_command(return_cmd, name='return')
cli.add_command(transfer_cmd, name='transfer')
cli.add_command(repair_start_cmd, name='repair')
cli.add_command(repair_complete_cmd, name='repair-complete')
cli.add_command(repair_list_cmd, name='repair-list')
cli.add_command(repair_cost_cmd, name='repair-cost')
cli.add_command(repair_summary_cmd, name='repair-summary')
cli.add_command(batch_cmd, name='batch')
cli.add_command(batch_template_cmd, name='batch-template')
cli.add_command(move_cmd, name='move')
cli.add_command(remark_cmd, name='remark')
cli.add_command(tag_cmd, name='tag')
cli.add_command(status_cmd, name='status')
cli.add_command(depreciation_cmd, name='depreciation')
cli.add_command(scrap_cmd, name='scrap')
cli.add_command(idle_cmd, name='idle')
cli.add_command(report_cmd, name='report')
cli.add_command(inventory_diff_cmd, name='inventory-diff')
cli.add_command(history_cmd, name='history')
cli.add_command(export_cmd, name='export')
cli.add_command(monthly_report_cmd, name='monthly-report')


def main():
    cli()


if __name__ == '__main__':
    main()
