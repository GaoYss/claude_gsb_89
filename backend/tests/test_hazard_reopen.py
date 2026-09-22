"""已销号隐患申请重启的接口测试。"""

from datetime import date, timedelta

from tests.conftest import API


def _create_closed_hazard(client, reservoir_id: int) -> dict:
    hazard = client.post(
        f"{API}/hazards",
        json={"reservoir_id": reservoir_id, "title": "排水沟开裂", "category": "slope"},
    ).json()
    closed = client.post(
        f"{API}/hazards/{hazard['id']}/transition",
        json={"target_status": "closed", "content": "重新砌筑完成，验收通过"},
    )
    assert closed.status_code == 200, closed.text
    return closed.json()


def test_reopen_requires_closed_status(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = client.post(
        f"{API}/hazards",
        json={"reservoir_id": reservoir["id"], "title": "新隐患", "category": "dam_body"},
    ).json()

    response = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "再次出现", "basis": "巡查记录", "confirmed": True},
    )
    assert response.status_code == 409
    assert "只有已销号" in response.json()["detail"]


def test_reopen_requires_reason_basis_and_confirmation(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _create_closed_hazard(client, reservoir["id"])

    missing_fields = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "", "basis": "", "confirmed": True},
    )
    assert missing_fields.status_code == 422

    no_confirm = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={
            "reason": "原位置相邻 2 米再次开裂",
            "basis": "9 月巡查记录及现场照片",
            "confirmed": False,
        },
    )
    assert no_confirm.status_code == 422
    assert "确认" in no_confirm.json()["detail"]


def test_reopen_creates_new_cycle_and_keeps_history(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _create_closed_hazard(client, reservoir["id"])
    original_record_count = len(hazard["rectifications"])
    first_cycle = hazard["cycles"][0]

    response = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={
            "reason": "原位置相邻 2 米排水沟再次出现纵向裂缝",
            "basis": "本月日常巡查记录、现场复核照片，经镇水利站确认",
            "operator": "陈立",
            "confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # 主单回到待整改，销号日期清空，累计重启次数 +1
    assert body["status"] == "registered"
    assert body["closed_on"] is None
    assert body["reopen_count"] == 1
    assert body["cycle_seq"] == 2
    assert body["can_reopen"] is False
    assert body["is_reopened"] is True
    assert body["is_overdue"] is False

    # 原有流水全部保留，并新增一条「重启整改」流水（归属第 2 轮）
    assert len(body["rectifications"]) == original_record_count + 1
    reopen_record = body["rectifications"][-1]
    assert reopen_record["action"] == "reopen"
    assert reopen_record["status_from"] == "closed"
    assert reopen_record["status_to"] == "registered"
    assert reopen_record["cycle_seq"] == 2
    assert "纵向裂缝" in reopen_record["content"]
    assert "日常巡查记录" in reopen_record["content"]
    assert body["rectifications"][0]["cycle_seq"] == 1

    # 两个轮次：首轮保留历史销号日期，新一轮在办
    assert len(body["cycles"]) == 2
    assert body["cycles"][0]["seq"] == 1
    assert body["cycles"][0]["closed_on"] == first_cycle["closed_on"]
    assert body["cycles"][0]["is_reopen"] is False
    second = body["cycles"][1]
    assert second["seq"] == 2
    assert second["closed_on"] is None
    assert second["started_on"] == date.today().isoformat()
    assert second["is_reopen"] is True
    assert "再次出现纵向裂缝" in second["reopen_reason"]
    assert "镇水利站" in second["reopen_basis"]


def test_duplicate_reopen_while_open_is_rejected(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _create_closed_hazard(client, reservoir["id"])

    payload = {
        "reason": "同类问题再次出现",
        "basis": "巡查记录",
        "confirmed": True,
    }
    first = client.post(f"{API}/hazards/{hazard['id']}/reopen", json=payload)
    assert first.status_code == 200

    # 在办期间重复发起重启：拒绝，不产生第二条整改任务
    duplicate = client.post(f"{API}/hazards/{hazard['id']}/reopen", json=payload)
    assert duplicate.status_code == 409
    detail = client.get(f"{API}/hazards/{hazard['id']}").json()
    assert len(detail["cycles"]) == 2
    assert detail["reopen_count"] == 1


def test_reopened_hazard_can_close_and_reopen_again(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _create_closed_hazard(client, reservoir["id"])

    client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "再次开裂", "basis": "巡查记录", "confirmed": True},
    )
    # 第 2 轮销号
    second_close = client.post(
        f"{API}/hazards/{hazard['id']}/transition",
        json={"target_status": "closed", "content": "扩大范围重砌完成"},
    )
    assert second_close.status_code == 200
    assert second_close.json()["closed_on"] == date.today().isoformat()

    # 再次销号后可以发起第 3 轮
    third = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "又一次出现", "basis": "专项检查通报", "confirmed": True},
    )
    assert third.status_code == 200
    body = third.json()
    assert body["reopen_count"] == 2
    assert body["cycle_seq"] == 3
    assert len(body["cycles"]) == 3
    assert body["cycles"][0]["closed_on"] is not None
    assert body["cycles"][1]["closed_on"] is not None
    assert body["cycles"][2]["closed_on"] is None


def test_reopened_hazard_no_longer_counted_as_closed(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _create_closed_hazard(client, reservoir["id"])

    before = client.get(f"{API}/overview/summary").json()
    assert before["hazard_open"] == 0

    client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "再次出现", "basis": "巡查记录", "confirmed": True},
    )

    after = client.get(f"{API}/overview/summary").json()
    assert after["hazard_open"] == 1
    status_counts = {item["value"]: item["count"] for item in after["hazard_by_status"]}
    assert status_counts["closed"] == 0
    assert status_counts["registered"] == 1

    # 列表 open_only 能查到重启后的隐患
    page = client.get(f"{API}/hazards", params={"open_only": True}).json()
    assert page["total"] == 1
    assert page["items"][0]["id"] == hazard["id"]


def test_manual_reopen_record_is_rejected(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = client.post(
        f"{API}/hazards",
        json={"reservoir_id": reservoir["id"], "title": "新隐患", "category": "dam_body"},
    ).json()

    response = client.post(
        f"{API}/hazards/{hazard['id']}/rectifications",
        json={"action": "reopen", "content": "手工伪造重启记录"},
    )
    assert response.status_code == 422
    assert "系统自动生成" in response.json()["detail"]


def test_reopened_hazard_supports_rectification_flow(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _create_closed_hazard(client, reservoir["id"])
    client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "再次出现", "basis": "巡查记录", "confirmed": True},
    )

    # 重启后可以继续追加整改记录、走状态机
    add = client.post(
        f"{API}/hazards/{hazard['id']}/rectifications",
        json={"action": "measure", "content": "重新进场处理"},
    )
    assert add.status_code == 201
    assert add.json()["status"] == "rectifying"
    assert add.json()["rectifications"][-1]["cycle_seq"] == 2


def test_rectification_stats_split_by_cohort(client, make_reservoir):
    reservoir = make_reservoir()
    first = _create_closed_hazard(client, reservoir["id"])
    second = _create_closed_hazard(client, reservoir["id"])
    # 第二条重启，新一轮在办
    client.post(
        f"{API}/hazards/{second['id']}/reopen",
        json={"reason": "再次出现", "basis": "巡查记录", "confirmed": True},
    )

    summary = client.get(f"{API}/overview/summary").json()
    stats = summary["rectification"]
    # 首轮：2 轮全部已闭环
    assert stats["first"]["total"] == 2
    assert stats["first"]["closed"] == 2
    assert stats["first"]["open"] == 0
    assert stats["first"]["closure_rate"] == 1.0
    # 重启后：1 轮在办，未闭环
    assert stats["reopened"]["total"] == 1
    assert stats["reopened"]["closed"] == 0
    assert stats["reopened"]["open"] == 1
    assert stats["reopened"]["closure_rate"] == 0.0
    assert stats["reopened"]["avg_handling_days"] is None
    assert stats["reopen_hazard_count"] == 1
    # 首轮平均办理时长可以算出（天）
    assert stats["first"]["avg_handling_days"] is not None
    assert stats["first"]["avg_handling_days"] >= 0


def test_monthly_report_is_immutable_after_reopen(client, db_session, make_reservoir):
    """上月已销号的隐患本月重启：上月月报仍按已闭环统计，本月才出现重启轮次。"""
    from sqlalchemy import select

    from app.models import Hazard, HazardRectificationCycle

    reservoir = make_reservoir()
    # 直接构造一条「上月销号」的隐患
    today = date.today()
    first_of_this_month = today.replace(day=1)
    last_month_date = first_of_this_month - timedelta(days=1)
    year, month = last_month_date.year, last_month_date.month

    hazard = client.post(
        f"{API}/hazards",
        json={
            "reservoir_id": reservoir["id"],
            "title": "历史月报隐患",
            "category": "dam_body",
            "discovered_on": (last_month_date - timedelta(days=10)).isoformat(),
        },
    ).json()

    # 把首轮标记为上月销号（模拟历史数据）
    cycle = db_session.scalar(
        select(HazardRectificationCycle).where(
            HazardRectificationCycle.hazard_id == hazard["id"]
        )
    )
    cycle.closed_on = last_month_date
    db_session.get(Hazard, hazard["id"]).status = "closed"
    db_session.get(Hazard, hazard["id"]).closed_on = last_month_date
    db_session.commit()

    # 上月月报：首轮 1 个任务、已闭环
    report_before = client.get(
        f"{API}/overview/rectification-monthly", params={"year": year, "month": month}
    ).json()
    assert report_before["first"]["closed"] == 1
    assert report_before["first"]["closure_rate"] == 1.0
    assert report_before["reopened"]["total"] == 0

    # 本月重启
    client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "同类问题再现", "basis": "巡查记录", "confirmed": True},
    )

    # 重新查询上月月报：结果不被重启改写
    report_after = client.get(
        f"{API}/overview/rectification-monthly", params={"year": year, "month": month}
    ).json()
    assert report_after == report_before

    # 本月月报：首轮仍是 1 个历史已闭环任务，重启轮次 1 个在办
    this_month = client.get(
        f"{API}/overview/rectification-monthly",
        params={"year": today.year, "month": today.month},
    ).json()
    assert this_month["first"]["closed"] == 1
    assert this_month["reopened"]["total"] == 1
    assert this_month["reopened"]["started_in_period"] == 1
    assert this_month["reopened"]["closed"] == 0
