from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import render
import requests
from .models import AssistantSession, AssistantMessage, ChatMessage, DifyConfig
from .serializers import (
    AssistantSessionSerializer, 
    AssistantSessionCreateSerializer,
    AssistantMessageSerializer,
    ChatMessageSerializer
)


class AssistantSessionViewSet(viewsets.ModelViewSet):
    """智能助手会话视图集"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return AssistantSessionCreateSerializer
        return AssistantSessionSerializer
    
    def get_queryset(self):
        return AssistantSession.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['post'])
    def add_message(self, request, pk=None):
        """添加消息到会话"""
        session = self.get_object()
        serializer = AssistantMessageSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.save(session=session)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        """获取会话的聊天消息"""
        session = self.get_object()
        messages = session.chat_messages.all()
        serializer = ChatMessageSerializer(messages, many=True)
        return Response(serializer.data)


class ChatViewSet(viewsets.ViewSet):
    """聊天功能ViewSet"""
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['post'])
    def send_message(self, request):
        """发送消息到Dify API"""
        session_id = request.data.get('session_id')
        message = request.data.get('message')
        
        if not session_id or not message:
            return Response(
                {'error': 'session_id和message都是必填项'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 获取会话
        try:
            session = AssistantSession.objects.get(
                session_id=session_id,
                user=request.user
            )
        except AssistantSession.DoesNotExist:
            return Response(
                {'error': '会话不存在'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # 获取Dify配置
        dify_config = DifyConfig.get_active_config()
        if not dify_config:
            return Response(
                {'error': '未配置Dify API，请先在配置中心配置'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 保存用户消息
        user_message = ChatMessage.objects.create(
            session=session,
            role='user',
            content=message,
            conversation_id=session.conversation_id
        )
        
        try:
            # 调用Dify API
            headers = {
                'Authorization': f'Bearer {dify_config.api_key}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'inputs': {},
                'query': message,
                'user': str(request.user.id),
                'response_mode': 'blocking'
            }
            
            # 如果有conversation_id，添加到请求中以保持会话连续性
            if session.conversation_id:
                payload['conversation_id'] = session.conversation_id
            
            # 去除URL末尾的斜杠
            api_url = dify_config.api_url.rstrip('/')
            
            response = requests.post(
                f'{api_url}/chat-messages',
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # 更新会话的conversation_id
                if 'conversation_id' in data and not session.conversation_id:
                    session.conversation_id = data['conversation_id']
                    session.save()
                
                # 保存助手回复
                assistant_message = ChatMessage.objects.create(
                    session=session,
                    role='assistant',
                    content=data.get('answer', ''),
                    conversation_id=data.get('conversation_id'),
                    message_id=data.get('message_id')
                )
                
                return Response({
                    'user_message': ChatMessageSerializer(user_message).data,
                    'assistant_message': ChatMessageSerializer(assistant_message).data,
                    'conversation_id': data.get('conversation_id')
                })
            else:
                return Response({
                    'error': f'Dify API错误: {response.status_code}',
                    'detail': response.text
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except requests.exceptions.Timeout:
            return Response({
                'error': 'API请求超时'
            }, status=status.HTTP_408_REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            return Response({
                'error': f'API请求失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def assistant_view(request):
    """智能助手页面视图 - 用于iframe内嵌"""
    return render(request, 'assistant/assistant.html')


# ==================== Dify Agent 工具回调端点 ====================
# 供 Dify 工作流中的 HTTP 工具调用，由 Dify 平台直接 POST 请求

import json as _json
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

INTERNAL_KEY = "testhub-appium-2026"  # Dify HTTP 工具 Header 中携带


@csrf_exempt
def appium_tool_execute(request):
    """
    Dify Agent 工具回调端点
    接收 Dify HTTP 工具的 POST 请求，在真机上执行 Appium 操作
    """
    # 内部 key 认证
    if request.headers.get("X-Internal-Key", "") != INTERNAL_KEY:
        return JsonResponse({"error": "unauthorized"}, status=401)

    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    try:
        body = _json.loads(request.body.decode("utf-8"))
    except _json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    tool_name = body.get("tool_name", "")
    params = body.get("parameters", {})

    if not tool_name:
        return JsonResponse({"error": "missing tool_name"}, status=400)

    try:
        from .appium_tools import AppiumToolExecutor
        executor = AppiumToolExecutor()
        result = executor.execute(tool_name, params)
        return JsonResponse({
            "success": result.success,
            "message": result.message,
            "data": result.data,
        })
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)}, status=500)
