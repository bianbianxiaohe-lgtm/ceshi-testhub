"""
API Agent 异步任务（Celery）

大文件解析、批量对比等耗时操作走 Celery 异步执行。
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def async_import_spec(self, project_id: str, spec_json: dict, spec_name: str,
                      spec_version: str, spec_format: str, file_name: str, user_id: str):
    """异步导入大型 API 文档"""
    from .agent import APIAgent

    try:
        result = APIAgent.execute_tool(
            'import_spec',
            project_id=project_id,
            spec_json=spec_json,
            name=spec_name,
            version=spec_version,
            format=spec_format,
            file_name=file_name,
            user=user_id,
        )
        return result
    except Exception as e:
        logger.error(f'async_import_spec 失败: {e}')
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=10)
        return {'error': str(e)}


@shared_task(bind=True, max_retries=2)
def async_diff_specs(self, old_spec_id: str, new_spec_id: str):
    """异步对比两个 API 文档版本"""
    from .agent import APIAgent
    from .models import APISpec

    try:
        new_spec = APISpec.objects.get(id=new_spec_id)
        result = APIAgent.execute_tool(
            'diff_specs',
            old_spec_id=old_spec_id,
            new_spec_id=new_spec_id,
            project_id=new_spec.project_id,
        )
        return result
    except Exception as e:
        logger.error(f'async_diff_specs 失败: {e}')
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=10)
        return {'error': str(e)}
