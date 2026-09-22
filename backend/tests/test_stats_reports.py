"""整改轮次统计与月报快照测试。"""

from datetime import date

from tests.conftest import API


def _register(client, reservoir_id: int, **overrides) -> dict:
    payload = {
        "reservoir_id": reservoir_id,
        "title": "测试隐患",
        "category": "dam_body",
        "severity": "general",
    }
    payload.update(overrides)
    response = client.post(f"{API}/hazards", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _close_direct(client, hazard_id: int, content: str = "已立行立改完成") -> None:
    response = client.post(
        f"{API}/hazards/{hazard_id}/transition",
        json={"target_status": "closed", "content": content},
    )
    assert response.status_code == 200, response.text


def _confirm_reopen(client, hazard_id: int, *, reason: str, evidence: str) -> None:
    applied = client.post(
        f"{API}/hazards/{hazard_id}/reopen", json={"reason": reason}
    )
    assert applied.status_code == 201, applied.text
    reopen_id = applied.json()["id"]
    reviewed = client.post(
        f"{API}/hazards/reopens/{reopen_id}/review",
        json={"decision": "confirmed", "evidence": evidence},
    )
    assert reviewed.status_code == 200, reviewed.text


def test_cycle_stats_split_first_and_reopened_rounds(client, make_reservoir):
    reservoir = make_reservoir()

    # 隐患 A：首轮销号后重启，当前仍在第 2 轮整改中
    hazard_a = _register(client, reservoir["id"], title="复发隐患")
    _close_direct(client, hazard_a["id"], "首轮处理完成")
    _confirm_reopen(
        client,
        hazard_a["id"],
        reason="原位置问题再次出现",
        evidence="现场复核确认复发",
    )

    # 隐患 B：首轮正常销号
    hazard_b = _register(client, reservoir["id"], title="一次闭环隐患")
    _close_direct(client, hazard_b["id"], "处理完成销号")

    stats = client.get(f"{API}/stats/rectification").json()

    first = stats["first_round"]
    assert first["entered"] == 2
    # 首轮当前仍闭环的只有 B；A 首轮销号后已重启
    assert first["closed_current"] == 1
    assert first["closed_cycles"] == 2
    assert first["reopened_after_close"] == 1
    assert first["in_progress"] == 0
    assert first["closure_rate"] == 0.5
    assert first["avg_handling_days"] is not None

    reopened = stats["reopened_round"]
    assert reopened["entered"] == 1
    assert reopened["in_progress"] == 1
    assert reopened["closed_current"] == 0
    assert reopened["closure_rate"] == 0.0
    assert reopened["avg_handling_days"] is None

    assert [item["scope"] for item in stats["round_detail"]] == [
        "first_round",
        "reopened_round",
    ]


def test_reopened_round_closure_rate_independent(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _register(client, reservoir["id"])
    _close_direct(client, hazard["id"], "首轮销号")
    _confirm_reopen(
        client, hazard["id"], reason="问题再次复发", evidence="复核确认复发并附照片"
    )
    # 第 2 轮再次销号
    _close_direct(client, hazard["id"], "第 2 轮整改完成销号")

    stats = client.get(f"{API}/stats/rectification").json()
    assert stats["first_round"]["closed_current"] == 0
    assert stats["first_round"]["reopened_after_close"] == 1
    reopened = stats["reopened_round"]
    assert reopened["entered"] == 1
    assert reopened["closed_current"] == 1
    assert reopened["closed_cycles"] == 1
    assert reopened["closure_rate"] == 1.0
    assert reopened["avg_handling_days"] == 0.0


def test_reopened_hazard_not_counted_as_closed(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _register(client, reservoir["id"])
    _close_direct(client, hazard["id"], "首轮销号")
    _confirm_reopen(
        client, hazard["id"], reason="同类问题再次出现", evidence="现场复核确认"
    )

    summary = client.get(f"{API}/overview/summary").json()
    assert summary["hazard_total"] == 1
    assert summary["hazard_closed"] == 0
    assert summary["hazard_open"] == 1
    assert summary["hazard_reopened"] == 1
    status_counts = {item["value"]: item["count"] for item in summary["hazard_by_status"]}
    assert status_counts["registered"] == 1
    assert status_counts["closed"] == 0

    open_page = client.get(f"{API}/hazards", params={"open_only": True}).json()
    assert open_page["total"] == 1
    closed_page = client.get(f"{API}/hazards", params={"status": "closed"}).json()
    assert closed_page["total"] == 0


def test_monthly_report_is_frozen_snapshot(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _register(client, reservoir["id"], title="当月销号后又重启的隐患")
    _close_direct(client, hazard["id"], "首轮处理完成销号")

    period = date.today().strftime("%Y-%m")

    # 生成月报时隐患已销号：快照记录已销号 1 条
    generated = client.post(
        f"{API}/stats/monthly-reports",
        json={"period": period, "generated_by": "统计员"},
    )
    assert generated.status_code == 200, generated.text
    snapshot = generated.json()["data"]
    assert snapshot["hazard_closed"] == 1
    assert snapshot["hazard_reopened"] == 0
    assert snapshot["cycle_stats"]["first_round"]["closed_current"] == 1

    # 之后隐患被重启并重新进入整改
    _confirm_reopen(
        client, hazard["id"], reason="同类问题再次出现", evidence="复核确认原问题复发"
    )

    # 已出的月报内容不被改写
    frozen = client.get(f"{API}/stats/monthly-reports/{period}").json()
    assert frozen["data"]["hazard_closed"] == 1
    assert frozen["data"]["hazard_reopened"] == 0
    assert frozen["generated_by"] == "统计员"

    listing = client.get(f"{API}/stats/monthly-reports").json()
    assert [item["period"] for item in listing] == [period]

    # 同期重复生成默认拒绝
    duplicate = client.post(f"{API}/stats/monthly-reports", json={"period": period})
    assert duplicate.status_code == 409

    # 实时统计已经反映重启后的状态
    summary = client.get(f"{API}/overview/summary").json()
    assert summary["hazard_closed"] == 0
    assert summary["hazard_reopened"] == 1

    # 显式覆盖才会按当前口径重算
    overwritten = client.post(
        f"{API}/stats/monthly-reports",
        json={"period": period, "overwrite": True, "remark": "重启后重算"},
    )
    assert overwritten.status_code == 200
    assert overwritten.json()["data"]["hazard_closed"] == 0
    assert overwritten.json()["data"]["hazard_reopened"] == 1
    assert overwritten.json()["remark"] == "重启后重算"


def test_monthly_report_not_found(client):
    response = client.get(f"{API}/stats/monthly-reports/2020-01")
    assert response.status_code == 404


def test_monthly_report_validates_period(client):
    bad = client.post(f"{API}/stats/monthly-reports", json={"period": "2026/09"})
    assert bad.status_code == 422
