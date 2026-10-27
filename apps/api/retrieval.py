"""Owner-filtered small-corpus retrieval with persistent, versioned embeddings."""
import hashlib
import math
import os
import re

MODEL = 'text-embedding-3-small'
DIMENSIONS = 256


def embed(texts):
    from openai import OpenAI
    client = OpenAI(timeout=30, max_retries=1)
    vectors = []
    for offset in range(0, len(texts), 32):
        response = client.embeddings.create(model=MODEL, dimensions=DIMENSIONS, input=texts[offset:offset + 32], encoding_format='float')
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
    if len(vectors) != len(texts) or any(len(v) != DIMENSIONS or not all(math.isfinite(x) for x in v) for v in vectors):
        raise ValueError('Invalid embedding response')
    return vectors


def index_document(document_id, data, semantic=False):
    chunks = []
    for page, text in enumerate(data['pages'], 1):
        for offset in range(0, len(text), 1200):
            piece = text[offset:offset + 1400].strip()
            if piece:
                chunks.append({'chunk_id': hashlib.sha256(f'{document_id}:{page}:{offset}'.encode()).hexdigest(), 'page': page, 'text': piece})
    if len(chunks) > 128:
        raise ValueError('Document has too many chunks')
    if semantic and chunks:
        for chunk, vector in zip(chunks, embed([c['text'] for c in chunks])):
            chunk['embedding'] = vector
    return {**data, 'chunks': chunks, 'index_version': 'chunks-1400-overlap200-v1', 'embedding_model': MODEL if semantic else None, 'embedding_dimensions': DIMENSIONS if semantic else None}


def cosine(a, b):
    denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / denominator if denominator else 0


def search(records, query, limit=12, semantic=False, query_vector=None):
    # records MUST already have been filtered by authenticated owner AND course.
    candidates = []
    terms = re.findall(r'\w+', query.casefold())
    query_vector = query_vector or (embed([query])[0] if semantic and records else None)
    for meta, data in records:
        chunks = data.get('chunks') or index_document(meta['id'], data)['chunks']
        compatible = data.get('embedding_model') == MODEL and data.get('embedding_dimensions') == DIMENSIONS
        for chunk in chunks:
            words = re.findall(r'\w+', chunk['text'].casefold())
            lexical = sum(term in chunk['text'].casefold() or any(len(word) >= 3 and word in term for word in words) for term in terms) / max(1, len(terms))
            similarity = cosine(query_vector, chunk['embedding']) if query_vector and compatible and chunk.get('embedding') else 0
            if lexical == 0 and similarity < 0.25:
                continue
            citation = {k: chunk[k] for k in ('chunk_id', 'page', 'text')}
            citation.update(document_id=meta['id'], filename=meta['filename'])
            candidates.append((0.7*similarity + 0.3*lexical, citation))
    candidates.sort(key=lambda pair: (-pair[0], pair[1]['chunk_id']))
    return [citation for _, citation in candidates[:limit]]
