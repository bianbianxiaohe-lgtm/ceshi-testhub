"""本地 bge-reranker 服务（放其他盘运行，避免占用 Docker 盘）。

启动：D:\\testhub-reranker\\venv\\Scripts\\python.exe scripts\\reranker_server.py
接口：POST /v1/rerank  （兼容 SiliconFlow 格式）
"""

import math

from fastapi import FastAPI
from pydantic import BaseModel

MODEL_DIR = r'D:\testhub-reranker\models\bge-reranker-base'

app = FastAPI(title='TestHub Local Reranker')


class RerankRequest(BaseModel):
    model: str = 'BAAI/bge-reranker-base'
    query: str = ''
    documents: list = []
    top_n: int = 5


_reranker = None


def get_reranker():
    global _reranker
    if _reranker is None:
        from FlagEmbedding import FlagReranker

        _reranker = FlagReranker(MODEL_DIR, use_fp16=False)
    return _reranker


def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 1.0 if x > 0 else 0.0


@app.post('/v1/rerank')
def rerank(req: RerankRequest):
    if not req.documents:
        return {'results': []}
    pairs = [[req.query, d] for d in req.documents]
    scores = get_reranker().compute_score(pairs)
    if isinstance(scores, float):
        scores = [scores]
    results = []
    for i, s in enumerate(scores):
        results.append(
            {'index': i, 'relevance_score': round(_sigmoid(float(s)), 6), 'raw_score': float(s)}
        )
    results.sort(key=lambda x: x['relevance_score'], reverse=True)
    return {'results': results[: req.top_n]}


@app.get('/health')
def health():
    return {'status': 'ok', 'model': MODEL_DIR}


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=8002)
