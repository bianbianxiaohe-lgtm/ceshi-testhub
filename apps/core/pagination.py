"""
标准分页类：在默认 PageNumberPagination 基础上允许客户端通过
page_size 查询参数自定义每页条数（上限 max_page_size），避免部分
列表接口（如用例详情页导航用的全量邻居列表）被固定 PAGE_SIZE 截断。
"""
from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 1000
