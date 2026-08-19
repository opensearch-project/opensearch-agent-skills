"""Tests for vector_sizing.py — no cluster required."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import json

from vector_sizing import (
    calculate_vector_memory_gb,
    calculate_storage_gb,
    usable_memory_gb,
    recommend_instances,
    calculate_shards,
    load_pricing,
    PRICING_META,
    BYTES_PER_ELEMENT,
    ENGINE_OVERHEAD,
    HNSW_M_DEFAULT,
    INSTANCE_CATALOGS,
)


class TestMemoryCalculation:
    """Test HNSW memory footprint calculations.

    Formula: 1.1 * (bytes_per_element * dimension + 8 * m) * num_vectors
    """

    def test_docs_example(self):
        """Match OpenSearch docs: 1M vectors, 256 dims, m=16 -> ~1.18 GiB."""
        mem = calculate_vector_memory_gb(1_000_000, 256, "fp32", "faiss", 16)
        # 1.1 * (4*256 + 8*16) * 1M = 1,267,200,000 bytes = 1.18 GiB
        assert 1.17 < mem < 1.19

    def test_basic_fp32_memory(self):
        """100M vectors x 768 dims x FP32."""
        mem = calculate_vector_memory_gb(100_000_000, 768, "fp32", "faiss")
        # 1.1 * (4*768 + 8*16) * 100M = 1.1 * 3200 * 100M = 352B bytes = 327.8 GiB
        assert 325 < mem < 330

    def test_fp16_reduces_memory(self):
        """FP16 should significantly reduce memory vs FP32."""
        fp32 = calculate_vector_memory_gb(100_000_000, 768, "fp32", "faiss")
        fp16 = calculate_vector_memory_gb(100_000_000, 768, "fp16", "faiss")
        # FP16: 1.1 * (2*768 + 8*16) * 100M — vector part halves but graph overhead stays
        assert fp16 < fp32
        # Ratio depends on dims — not exactly 0.5 because 8*m is constant
        ratio = fp16 / fp32
        assert 0.49 < ratio < 0.53

    def test_sq8_reduces_memory(self):
        """SQ8 should reduce memory significantly vs FP32."""
        fp32 = calculate_vector_memory_gb(100_000_000, 768, "fp32", "faiss")
        sq8 = calculate_vector_memory_gb(100_000_000, 768, "sq8", "faiss")
        assert sq8 < fp32
        ratio = sq8 / fp32
        assert 0.24 < ratio < 0.30

    def test_pq_reduces_memory_most(self):
        """PQ should give the largest memory reduction."""
        fp32 = calculate_vector_memory_gb(100_000_000, 768, "fp32", "faiss")
        pq = calculate_vector_memory_gb(100_000_000, 768, "pq", "faiss")
        assert pq < fp32
        ratio = pq / fp32
        assert 0.12 < ratio < 0.18

    def test_engine_overhead_nmslib(self):
        """nmslib should add 5% overhead vs FAISS."""
        faiss = calculate_vector_memory_gb(100_000_000, 768, "fp32", "faiss")
        nmslib = calculate_vector_memory_gb(100_000_000, 768, "fp32", "nmslib")
        ratio = nmslib / faiss
        assert 1.04 < ratio < 1.06

    def test_engine_overhead_lucene(self):
        """Lucene should add 15% overhead vs FAISS."""
        faiss = calculate_vector_memory_gb(100_000_000, 768, "fp32", "faiss")
        lucene = calculate_vector_memory_gb(100_000_000, 768, "fp32", "lucene")
        ratio = lucene / faiss
        assert 1.14 < ratio < 1.16

    def test_vectors_scale_linearly(self):
        """Doubling vectors should double memory."""
        mem_100m = calculate_vector_memory_gb(100_000_000, 768, "fp32", "faiss")
        mem_200m = calculate_vector_memory_gb(200_000_000, 768, "fp32", "faiss")
        ratio = mem_200m / mem_100m
        assert 1.99 < ratio < 2.01

    def test_zero_vectors(self):
        """Zero vectors should produce zero memory."""
        mem = calculate_vector_memory_gb(0, 768, "fp32", "faiss")
        assert mem == 0.0

    def test_m_parameter_affects_memory(self):
        """Higher M should increase memory (more neighbor connections)."""
        m16 = calculate_vector_memory_gb(100_000_000, 768, "fp32", "faiss", m=16)
        m32 = calculate_vector_memory_gb(100_000_000, 768, "fp32", "faiss", m=32)
        assert m32 > m16

    def test_large_scale_294m_1536(self):
        """294M x 1536 FP32 should be ~1.85-1.9 TB."""
        mem = calculate_vector_memory_gb(294_000_000, 1536, "fp32", "faiss")
        # 1.1 * (4*1536 + 8*16) * 294M = 1.1 * 6272 * 294M
        assert 1850 < mem < 1920


class TestUsableMemory:
    """Test usable memory calculations for instance types."""

    def test_small_instance_no_usable(self):
        """16 GB instance should have no usable memory."""
        usable = usable_memory_gb(16)
        assert usable == 0.0

    def test_384gb_instance(self):
        """384 GB instance: (384-31-2) * 0.70 = 245.7 GB usable."""
        usable = usable_memory_gb(384)
        expected = (384 - 31 - 2) * 0.70
        assert abs(usable - expected) < 0.1

    def test_768gb_instance(self):
        """768 GB instance: (768-31-2) * 0.70 = 514.5 GB usable."""
        usable = usable_memory_gb(768)
        expected = (768 - 31 - 2) * 0.70
        assert abs(usable - expected) < 0.1


class TestStorageCalculation:
    """Test storage requirement calculations."""

    def test_storage_includes_docs(self):
        """Storage should include both vector data and document overhead."""
        storage = calculate_storage_gb(1_000_000, 768, 1024, "fp32")
        vector_part = 1_000_000 * 768 * 4 / (1024**3)
        doc_part = 1_000_000 * 1024 / (1024**3)
        expected = vector_part + doc_part
        assert abs(storage - expected) < 0.1

    def test_quantization_reduces_storage(self):
        """FP16 storage should be less than FP32."""
        fp32 = calculate_storage_gb(10_000_000, 768, 1024, "fp32")
        fp16 = calculate_storage_gb(10_000_000, 768, 1024, "fp16")
        assert fp16 < fp32

    def test_source_data_overrides_doc_size(self):
        """source_data_gb should override per-doc calculation."""
        with_doc_size = calculate_storage_gb(1_000_000, 768, 1024, "fp32", source_data_gb=0)
        with_source = calculate_storage_gb(1_000_000, 768, 1024, "fp32", source_data_gb=50)
        assert with_source > with_doc_size


class TestShardCalculation:
    """Test shard strategy recommendations."""

    def test_small_dataset_one_shard(self):
        """10M vectors, small storage -> 1 shard."""
        result = calculate_shards(10_000_000, 20.0)
        assert result["primary_shards"] == 1

    def test_large_dataset_by_count(self):
        """294M vectors -> at least 10 shards by doc count."""
        result = calculate_shards(294_000_000, 30.0)
        assert result["primary_shards"] >= 10

    def test_large_storage_by_size(self):
        """2000 GB storage -> at least 40 shards by size."""
        result = calculate_shards(100_000_000, 2000.0)
        assert result["primary_shards"] >= 40

    def test_uses_max_of_criteria(self):
        """Should use whichever criterion gives more shards."""
        result = calculate_shards(10_000_000, 200.0)
        assert result["primary_shards"] == 4


class TestMultiCloudRecommendations:
    """Test instance recommendations across clouds."""

    def test_aws_opensearch_returns_results(self):
        """AWS OpenSearch Service should return recommendations."""
        recs = recommend_instances(500, 1, 2, 0, "aws-opensearch")
        assert len(recs) >= 1
        assert "search" in recs[0]["instance_type"]

    def test_aws_ec2_returns_results(self):
        """AWS EC2 should return recommendations."""
        recs = recommend_instances(500, 1, 2, 0, "aws-ec2")
        assert len(recs) >= 1

    def test_azure_returns_results(self):
        """Azure should return recommendations."""
        recs = recommend_instances(500, 1, 2, 0, "azure")
        assert len(recs) >= 1
        assert "Standard_" in recs[0]["instance_type"]

    def test_gcp_returns_results(self):
        """GCP should return recommendations."""
        recs = recommend_instances(500, 1, 2, 0, "gcp")
        assert len(recs) >= 1
        assert "n2" in recs[0]["instance_type"]

    def test_minimum_two_nodes(self):
        """Should never recommend fewer than 2 nodes (HA)."""
        for cloud in ["aws-ec2", "azure", "gcp"]:
            recs = recommend_instances(10, 1, 2, 0, cloud)
            for rec in recs:
                assert rec["nodes"] >= 2, f"Failed for {cloud}: {rec}"

    def test_multi_az_alignment(self):
        """Node count should be divisible by AZ count."""
        for cloud in ["aws-ec2", "azure", "gcp"]:
            recs = recommend_instances(500, 1, 2, 0, cloud)
            for rec in recs:
                assert rec["nodes"] % 2 == 0, f"Failed for {cloud}: {rec}"

    def test_three_az_alignment(self):
        """3-AZ should produce node counts divisible by 3."""
        for cloud in ["aws-ec2", "azure", "gcp"]:
            recs = recommend_instances(500, 1, 3, 0, cloud)
            for rec in recs:
                assert rec["nodes"] % 3 == 0, f"Failed for {cloud}: {rec}"

    def test_qps_increases_nodes(self):
        """Higher QPS should require more or equal nodes."""
        for cloud in ["aws-ec2", "azure", "gcp"]:
            recs_low = recommend_instances(100, 1, 2, 0, cloud)
            recs_high = recommend_instances(100, 1, 2, 10000, cloud)
            max_nodes_low = max(r["nodes"] for r in recs_low) if recs_low else 0
            max_nodes_high = max(r["nodes"] for r in recs_high) if recs_high else 0
            assert max_nodes_high >= max_nodes_low, f"Failed for {cloud}"

    def test_cost_is_positive(self):
        """Monthly cost should always be positive across all clouds."""
        for cloud in ["aws-opensearch", "aws-ec2", "azure", "gcp"]:
            recs = recommend_instances(500, 1, 2, 0, cloud)
            for rec in recs:
                assert rec["monthly_compute_usd"] > 0, f"Failed for {cloud}: {rec}"

    def test_all_catalogs_have_entries(self):
        """Each cloud catalog should have instance entries."""
        for cloud in ["aws-opensearch", "aws-ec2", "azure", "gcp"]:
            assert len(INSTANCE_CATALOGS[cloud]) > 0, f"Empty catalog for {cloud}"

    def test_self_managed_cheaper_than_managed(self):
        """Self-managed (EC2) should generally be cheaper than managed OpenSearch."""
        recs_managed = recommend_instances(500, 1, 2, 0, "aws-opensearch")
        recs_ec2 = recommend_instances(500, 1, 2, 0, "aws-ec2")
        if recs_managed and recs_ec2:
            cheapest_managed = recs_managed[0]["monthly_compute_usd"]
            cheapest_ec2 = recs_ec2[0]["monthly_compute_usd"]
            assert cheapest_ec2 < cheapest_managed


class TestPricingLoader:
    """Pricing is loaded from an external, dated file and can be overridden."""

    def test_bundled_pricing_has_provenance(self):
        """The bundled pricing.json loads with a real last_updated date."""
        catalogs = load_pricing()
        assert PRICING_META.get("last_updated") not in (None, "unknown", "embedded-fallback")
        assert PRICING_META.get("sources"), "sources should list provider pricing URLs"
        for cloud in ["aws-opensearch", "aws-ec2", "azure", "gcp"]:
            assert len(catalogs[cloud]) > 0

    def test_all_view_is_union_of_clouds(self):
        catalogs = load_pricing()
        expected = sum(len(catalogs[c]) for c in catalogs if c != "all")
        assert len(catalogs["all"]) == expected

    def test_prices_file_override(self, tmp_path):
        """A user-supplied prices file replaces the catalog and metadata."""
        custom = {
            "last_updated": "2099-01-01-TEST",
            "currency": "USD",
            "catalogs": {
                "aws-ec2": [
                    {"instance_type": "test.box", "vcpu": 64, "ram_gb": 512, "price_per_hour_usd": 1.0}
                ]
            },
        }
        p = tmp_path / "prices.json"
        p.write_text(json.dumps(custom))
        catalogs = load_pricing(str(p))
        assert catalogs["aws-ec2"] == [("test.box", 64, 512, 1.0)]
        assert PRICING_META["last_updated"] == "2099-01-01-TEST"

    def test_missing_explicit_file_raises(self):
        """An explicitly requested but missing prices file fails loudly."""
        import pytest
        with pytest.raises(SystemExit):
            load_pricing("/no/such/pricing/file.json")


class TestTierLabels:
    """Tier labels reflect instance size, not raw node count."""

    def test_largest_is_performance_smallest_is_economy(self):
        recs = recommend_instances(2000, 1, 2, 0, "aws-ec2")
        tiers = {r["tier"] for r in recs}
        # With several viable sizes we expect a spread of tiers, not all identical.
        assert tiers.issubset({"economy", "balanced", "performance"})
        if len(recs) >= 3:
            by_ram = sorted(recs, key=lambda r: r["ram_gb"])
            assert by_ram[0]["tier"] == "economy"
            assert by_ram[-1]["tier"] == "performance"
