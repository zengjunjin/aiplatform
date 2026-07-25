"""Tests for app.models.reranker_provider.LocalBgeRerankerProvider fallback path.

Task 2 SubTask 2.2: 验证 reranker fallback 在模型未加载时返回 list[tuple[int, float]]。
旧代码错误返回 list[tuple[int, int]] (enumerate(range(n)))，与基类契约
BaseRerankerProvider.rerank -> list[tuple[int, float]] 不一致，下游 Reranker.rerank
将其作为 score 写入 chunk["rerank_score"]，类型错误会导致序列化/排序异常。
"""

from app.models.reranker_provider import LocalBgeRerankerProvider


class TestRerankerFallback:
    def test_fallback_returns_tuple_int_float(self):
        """Task 2 SubTask 2.2: fallback 返回类型必须是 tuple[int, float]，idx 与 score 不相等

        回归测试: 旧代码 `list(enumerate(range(len(documents))))[:top_k]` 返回
        [(0, 0), (1, 1), (2, 2), ...]，其中 score 是 int（且 idx == score），
        既违反 list[tuple[int, float]] 契约，也让 idx/score 难以区分。
        正确实现应返回 [(0, 0.0), (1, 0.0), ...]，score 为 float 0.0。
        """
        provider = LocalBgeRerankerProvider()
        # 强制进入 fallback 分支：model 未加载
        provider._model = None

        documents = ["doc A", "doc B", "doc C", "doc D"]
        top_k = 3
        result = provider._rerank_sync("query", documents, top_k)

        # 1. 返回数量正确
        assert isinstance(result, list)
        assert len(result) == top_k

        # 2. 每个 element 是 tuple（不是 list），长度 2
        for item in result:
            assert isinstance(item, tuple), f"fallback 元素必须是 tuple，实际是 {type(item)}"
            assert len(item) == 2

        # 3. 类型契约：tuple[int, float] —— idx 是 int，score 是 float
        for idx, score in result:
            assert isinstance(idx, int), f"idx 必须是 int，实际是 {type(idx)}"
            assert isinstance(score, float), f"score 必须是 float，实际是 {type(score)}"

        # 4. idx 是文档原始索引（0..top_k-1，保持原顺序）
        idxs = [idx for idx, _ in result]
        assert idxs == list(range(top_k))

        # 5. 关键防退化断言：旧 bug `enumerate(range(n))` 返回 [(0, 0), (1, 1), (2, 2), ...]，
        #    其中 score == idx 对所有元素都成立，且 score 是 int。
        #    新实现返回 [(0, 0.0), (1, 0.0), (2, 0.0)]，score 全为 float 0.0。
        #    - 类型层面：score 必须是 float（旧 bug 是 int，已由断言 3 覆盖）
        #    - 行为层面：不允许所有元素都满足 score == idx（旧 bug 的特征）
        all_score_eq_idx = all(score == idx for idx, score in result)
        assert not all_score_eq_idx, (
            "不允许所有元素 score == idx；这是旧 bug enumerate(range(n)) 的特征，"
            "新实现 score 全为 0.0，idx > 0 时 score != idx"
        )
        # 对 idx >= 1 的元素，score(0.0) 必然不等于 idx（强化防退化）
        for idx, score in result:
            if idx >= 1:
                assert score != idx, (
                    f"idx >= 1 时 score ({score}) 不应等于 idx ({idx})；"
                    "旧 bug enumerate(range(n)) 会让两者相等"
                )
            assert score == 0.0, f"fallback score 应为 0.0，实际是 {score}"
