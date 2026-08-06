# -*- coding: utf-8 -*-
"""
墨刀技能 - 向量存储封装（方案 A：Chroma 嵌入式，零新容器）

Chroma 以 PersistentClient 跑在 backend 进程内，数据持久化到挂载卷
（docker-compose 中 testhub-chroma-data -> /app/chroma），容器重启不丢。
提供：
  - get_chroma_client()        获取全局单例客户端
  - get_merge_collection(sid)  获取某次三路合并的专用集合（余弦距离）
  - upsert_requirements(...)   批量写入需求向量
  - query_near_duplicates(...) 查询近邻（语义重复候选）
"""
import os
import logging

logger = logging.getLogger(__name__)

# 持久化路径：容器内默认 /app/chroma（已挂卷），本地开发可用环境变量覆盖
CHROMA_PERSIST_PATH = os.environ.get('CHROMA_PERSIST_PATH', '/app/chroma')

_client = None


def get_chroma_client():
    """获取（惰性初始化）Chroma 全局单例客户端。"""
    global _client
    if _client is None:
        import chromadb
        os.makedirs(CHROMA_PERSIST_PATH, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_PERSIST_PATH)
        logger.info(f'Chroma 客户端已初始化，持久化路径={CHROMA_PERSIST_PATH}')
    return _client


def get_merge_collection(session_id: str):
    """获取某次三路合并的专用集合（余弦距离空间）。"""
    client = get_chroma_client()
    name = f'modao_merge_{session_id}'
    return client.get_or_create_collection(
        name=name,
        metadata={'hnsw:space': 'cosine'},
    )


def release_merge_collection(session_id: str):
    """合并完成后释放集合，避免 chroma 长期占用内存。"""
    global _client
    if _client is None:
        return
    try:
        _client.delete_collection(f'modao_merge_{session_id}')
        logger.info(f'已释放合并集合 modao_merge_{session_id}')
    except Exception as e:  # 集合可能不存在
        logger.warning(f'释放合并集合失败（可忽略）: {e}')


def upsert_requirements(collection, items: list):
    """
    批量写入需求向量。
    items: [{'id': str, 'text': str, 'source': str, 'meta': dict}]
    """
    if not items:
        return
    ids = [str(it['id']) for it in items]
    embeddings = [it['vector'] for it in items]
    documents = [it.get('text', '') for it in items]
    metadatas = [
        {
            'source': it.get('source', ''),
            'text_preview': (it.get('text', '') or '')[:500],
            **(it.get('meta') or {}),
        }
        for it in items
    ]
    collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)


def query_near_duplicates(collection, vector: list, top_k: int = 5):
    """查询与给定向量最相似的 top_k 条（含自身，距离越小越相似）。"""
    res = collection.query(
        query_embeddings=[vector],
        n_results=min(top_k, collection.count() or 1),
        include=['distances', 'metadatas', 'documents'],
    )
    ids = res.get('ids', [[]])[0]
    distances = res.get('distances', [[]])[0]
    metadatas = res.get('metadatas', [[]])[0]
    documents = res.get('documents', [[]])[0]
    out = []
    for i, _id in enumerate(ids):
        out.append({
            'id': _id,
            'distance': distances[i],
            'similarity': 1.0 - distances[i],  # 余弦距离 -> 余弦相似度
            'source': (metadatas[i] or {}).get('source', ''),
            'text': documents[i] if documents else '',
        })
    return out


# ---------------------------------------------------------------------------
# 项目知识库 RAG 检索（方案 C）：按语义相似度召回 top-K 知识条目，
# 替代原先「全量灌入 prompt」的做法，解决同名不同义功能被错误召回的问题。
# 向量只存 Chroma，不落业务库，因此无需数据库迁移。
# ---------------------------------------------------------------------------

def get_project_kb_collection(project_id) -> 'Collection':
    """获取某项目的知识库专用向量集合（余弦距离空间）。"""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=f'kb_{project_id}',
        metadata={'hnsw:space': 'cosine'},
    )


def upsert_kb_item(collection, item_id: str, vector: list, document: str, metadata: dict):
    """写入/更新一条知识条目的向量。"""
    collection.upsert(
        ids=[str(item_id)],
        embeddings=[vector],
        documents=[document],
        metadatas=[metadata],
    )


def delete_kb_item(collection, item_id: str):
    """删除一条知识条目的向量（条目停用/删除时同步）。"""
    try:
        collection.delete(ids=[str(item_id)])
    except Exception as e:
        logger.warning(f'删除知识库向量失败（可忽略）: {e}')


def query_kb(collection, vector: list, top_k: int = 8) -> list:
    """检索与给定向量最相似的 top_k 条知识（按余弦相似度）。"""
    n = collection.count()
    if n == 0:
        return []
    res = collection.query(
        query_embeddings=[vector],
        n_results=min(top_k, n),
        include=['documents', 'metadatas'],
    )
    documents = (res.get('documents') or [[]])[0]
    metadatas = (res.get('metadatas') or [[]])[0]
    out = []
    for i, doc in enumerate(documents):
        out.append({
            'text': doc,
            'meta': metadatas[i] if i < len(metadatas) else {},
        })
    return out
