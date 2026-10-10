"""
Teste automatizado de perf_log.py: medição de duração por evento,
agregação por categoria (ordenada pelo maior consumidor de tempo),
registro de eventos que falham (com o erro anotado), e segurança entre
threads (já que a pré-busca de prévias e a montagem final processam
segmentos em paralelo).
"""
import json
import os
import threading
import time

import pytest

from perf_log import PerfLog


class TestPerfLogBasics:
    def test_records_duration_of_timed_block(self, tmp_path):
        perf = PerfLog(str(tmp_path), job_id="teste")
        with perf.timed("etapa_a"):
            time.sleep(0.05)
        path = perf.save()

        data = json.load(open(path))
        assert data["job_id"] == "teste"
        assert len(data["events"]) == 1
        assert data["events"][0]["event"] == "etapa_a"
        assert data["events"][0]["duration_seconds"] >= 0.04

    def test_records_metadata_passed_to_timed(self, tmp_path):
        perf = PerfLog(str(tmp_path))
        with perf.timed("busca", provider="pexels", query="dog"):
            pass
        path = perf.save()
        event = json.load(open(path))["events"][0]
        assert event["provider"] == "pexels"
        assert event["query"] == "dog"

    def test_records_event_that_raises_with_error_annotated(self, tmp_path):
        perf = PerfLog(str(tmp_path))
        with pytest.raises(ValueError):
            with perf.timed("etapa_que_falha"):
                raise ValueError("algo deu errado")
        path = perf.save()
        event = json.load(open(path))["events"][0]
        assert event["event"] == "etapa_que_falha"
        assert "algo deu errado" in event["error"]

    def test_record_method_for_precomputed_durations(self, tmp_path):
        perf = PerfLog(str(tmp_path))
        perf.record("etapa_manual", 1.234, nota="calculado fora do with")
        path = perf.save()
        event = json.load(open(path))["events"][0]
        assert event["duration_seconds"] == 1.234
        assert event["nota"] == "calculado fora do with"


class TestPerfLogAggregation:
    def test_aggregates_by_category_grouping_segment_index(self, tmp_path):
        """previa:segmento_0:busca e previa:segmento_1:busca devem cair
        na MESMA categoria (previa:segmento_N:busca), não em categorias
        separadas por índice."""
        perf = PerfLog(str(tmp_path))
        with perf.timed("previa:segmento_0:busca"):
            time.sleep(0.01)
        with perf.timed("previa:segmento_1:busca"):
            time.sleep(0.02)
        with perf.timed("previa:segmento_2:busca"):
            time.sleep(0.01)
        path = perf.save()

        totals = json.load(open(path))["totals_by_category_ordered_by_time"]
        assert "previa:segmento_N:busca" in totals
        assert totals["previa:segmento_N:busca"]["count"] == 3

    def test_orders_categories_by_total_time_descending(self, tmp_path):
        perf = PerfLog(str(tmp_path))
        with perf.timed("rapida"):
            time.sleep(0.01)
        with perf.timed("lenta"):
            time.sleep(0.08)
        path = perf.save()

        totals = json.load(open(path))["totals_by_category_ordered_by_time"]
        categories_in_order = list(totals.keys())
        assert categories_in_order[0] == "lenta", "a categoria que mais consumiu tempo deveria vir primeiro"

    def test_counts_errors_per_category(self, tmp_path):
        perf = PerfLog(str(tmp_path))
        for i in range(3):
            try:
                with perf.timed(f"previa:segmento_{i}:busca"):
                    if i == 1:
                        raise RuntimeError("falha simulada")
            except RuntimeError:
                pass
        path = perf.save()
        totals = json.load(open(path))["totals_by_category_ordered_by_time"]
        assert totals["previa:segmento_N:busca"]["count"] == 3
        assert totals["previa:segmento_N:busca"]["errors"] == 1


class TestPerfLogThreadSafety:
    def test_concurrent_writes_from_multiple_threads_are_not_lost(self, tmp_path):
        perf = PerfLog(str(tmp_path))

        def worker(i):
            with perf.timed(f"previa:segmento_{i}:busca"):
                time.sleep(0.02)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        path = perf.save()
        data = json.load(open(path))
        assert len(data["events"]) == 10

    def test_save_can_be_called_multiple_times_without_losing_earlier_events(self, tmp_path):
        perf = PerfLog(str(tmp_path))
        with perf.timed("etapa_1"):
            pass
        perf.save()
        with perf.timed("etapa_2"):
            pass
        path = perf.save()

        data = json.load(open(path))
        assert len(data["events"]) == 2
