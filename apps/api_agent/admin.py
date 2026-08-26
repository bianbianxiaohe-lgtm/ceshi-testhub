from django.contrib import admin
from .models import APISpec, APIEndpoint, APIChange, EndpointMapping


@admin.register(APISpec)
class APISpecAdmin(admin.ModelAdmin):
    list_display = ['name', 'version', 'project', 'spec_format', 'endpoint_count', 'created_at']
    list_filter = ['spec_format', 'created_at']
    search_fields = ['name', 'version', 'project__name']


@admin.register(APIEndpoint)
class APIEndpointAdmin(admin.ModelAdmin):
    list_display = ['full_identifier', 'summary', 'spec', 'tags']
    list_filter = ['method']
    search_fields = ['path', 'summary', 'spec__name']


@admin.register(APIChange)
class APIChangeAdmin(admin.ModelAdmin):
    list_display = ['severity', 'change_type', 'endpoint_method', 'endpoint_path', 'created_at']
    list_filter = ['severity', 'change_type', 'created_at']
    search_fields = ['endpoint_path', 'detail']


@admin.register(EndpointMapping)
class EndpointMappingAdmin(admin.ModelAdmin):
    list_display = ['endpoint', 'api_request', 'match_status', 'updated_at']
    list_filter = ['match_status']
    search_fields = ['endpoint__path', 'api_request__name']
