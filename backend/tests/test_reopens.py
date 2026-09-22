"""已销号隐患重启流程测试。"""

from datetime import date, timedelta

from tests.conftest import API


def _close_hazard(client, reservoir_id: int, **overrides) -> dict:
    payload = {
        "reservoir_id": reservoir_id,
        "title": "已整改销号的隐患",
        "category": "dam_body",
        "severity": "general",
    }
    payload.update(overrides)
    hazard = client.post(f"{API}/hazards", json=payload).json()
    closed = client.post(
        f"{API}/hazards/{hazard['id']}/transition",
        json={"target_status": "closed", "content": "立行立改，已处理完成", "operator": "李四"},
    )
    assert closed.status_code == 200, closed.text
    return closed.json()


def test_apply_reopen_requires_closed_hazard(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = client.post(
        f"{API}/hazards",
        json={"reservoir_id": reservoir["id"], "title": "未销号隐患", "category": "dam_body"},
    ).json()

    response = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "同类问题再次出现，坝顶原位置又出现裂缝"},
    )
    assert response.status_code == 409


def test_apply_and_confirm_reopen_flow(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _close_hazard(client, reservoir["id"])
    original_records = list(hazard["rectifications"])

    # 申请重启
    applied = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "近期巡查发现原裂缝位置附近再次出现横向裂缝约 1.5 米", "applicant": "张三"},
    )
    assert applied.status_code == 201, applied.text
    request = applied.json()
    assert request["status"] == "pending"
    assert request["round_no"] == 2
    assert request["previous_closed_on"] == date.today().isoformat()

    # 申请期间隐患仍保持已销号
    detail = client.get(f"{API}/hazards/{hazard['id']}").json()
    assert detail["status"] == "closed"

    # 确认重启必须填写依据
    missing = client.post(
        f"{API}/hazards/reopens/{request['id']}/review",
        json={"decision": "confirmed", "confirmer": "王科长"},
    )
    assert missing.status_code == 422
    assert "依据" in missing.json()["detail"]

    # 正式确认
    confirmed = client.post(
        f"{API}/hazards/reopens/{request['id']}/review",
        json={
            "decision": "confirmed",
            "evidence": "9 月 22 日现场复核，原裂缝下游侧 0.8 米处确有新生裂缝，附现场照片 3 张",
            "confirmer": "王科长",
            "review_comment": "同意重启，纳入新一轮整改",
            "deadline": (date.today() + timedelta(days=30)).isoformat(),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "registered"
    assert body["closed_on"] is None
    assert body["reopen_count"] == 1

    # 原整改流水保留，时间轴多出一条重启节点，轮次递增
    actions = [r["action"] for r in body["rectifications"]]
    assert actions[: len(original_records)] == [r["action"] for r in original_records]
    assert actions[-1] == "reopen"
    reopen_record = body["rectifications"][-1]
    assert reopen_record["status_from"] == "closed"
    assert reopen_record["status_to"] == "registered"
    assert reopen_record["round_no"] == 2
    assert all(r["round_no"] == 1 for r in body["rectifications"][:-1])

    # 申请记录已确认
    assert body["reopen_requests"][0]["status"] == "confirmed"
    assert "现场复核" in body["reopen_requests"][0]["evidence"]

    # 重启后可以继续整改流转，新流水属于第 2 轮
    started = client.post(
        f"{API}/hazards/{hazard['id']}/transition",
        json={"target_status": "rectifying", "operator": "李四"},
    )
    assert started.status_code == 200
    assert started.json()["rectifications"][-1]["round_no"] == 2


def test_duplicate_reopen_application_returns_same_request(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _close_hazard(client, reservoir["id"])

    first = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "同类问题再次出现，需要重新整改处理"},
    ).json()
    second = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "又写了一遍申请，原因略有不同"},
    )
    assert second.status_code == 201
    # 重复发起只返回同一条待确认申请，不产生新整改任务
    assert second.json()["id"] == first["id"]
    assert second.json()["reason"] == first["reason"]

    listing = client.get(f"{API}/hazards/reopens", params={"status": "pending"}).json()
    assert listing["total"] == 1


def test_reject_reopen_keeps_hazard_closed(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _close_hazard(client, reservoir["id"])
    request = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "怀疑同类问题再次出现"},
    ).json()

    rejected = client.post(
        f"{API}/hazards/reopens/{request['id']}/review",
        json={"decision": "rejected", "confirmer": "王科长", "review_comment": "现场复核为干缩裂缝，非原问题复发"},
    )
    assert rejected.status_code == 200
    body = rejected.json()
    assert body["status"] == "closed"
    assert body["reopen_count"] == 0
    assert body["reopen_requests"][0]["status"] == "rejected"
    assert all(r["action"] != "reopen" for r in body["rectifications"])

    # 驳回后可以重新发起申请
    again = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "再次发现同类问题，渗水重新出现"},
    )
    assert again.status_code == 201
    assert again.json()["status"] == "pending"


def test_cannot_review_reopen_twice(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _close_hazard(client, reservoir["id"])
    request = client.post(
        f"{API}/hazards/{hazard['id']}/reopen",
        json={"reason": "同类问题再次出现需要重启"},
    ).json()
    client.post(
        f"{API}/hazards/reopens/{request['id']}/review",
        json={"decision": "confirmed", "evidence": "现场复核确认原问题复发，有照片佐证"},
    )

    again = client.post(
        f"{API}/hazards/reopens/{request['id']}/review",
        json={"decision": "rejected", "review_comment": "重复提交"},
    )
    assert again.status_code == 409


def test_multiple_reopens_create_distinct_rounds(client, make_reservoir):
    reservoir = make_reservoir()
    hazard = _close_hazard(client, reservoir["id"])

    for expected_round in (2, 3):
        requests = client.get(
            f"{API}/hazards/reopens", params={"hazard_id": hazard["id"]}
        ).json()
        pending = next(
            item for item in requests["items"] if item["status"] == "pending"
        ) if any(item["status"] == "pending" for item in requests["items"]) else None

        if pending is None:
            applied = client.post(
                f"{API}/hazards/{hazard['id']}/reopen",
                json={"reason": f"第 {expected_round - 1} 轮整改后同类问题再次出现"},
            )
            assert applied.status_code == 201
            pending = applied.json()

        reviewed = client.post(
            f"{API}/hazards/reopens/{pending['id']}/review",
            json={"decision": "confirmed", "evidence": f"第 {expected_round - 1} 次现场复核确认问题复发"},
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["reopen_count"] == expected_round - 1

        # 再次销号
        closed = client.post(
            f"{API}/hazards/{hazard['id']}/transition",
            json={"target_status": "closed", "content": f"第 {expected_round} 轮整改完成销号"},
        )
        assert closed.status_code == 200

    detail = client.get(f"{API}/hazards/{hazard['id']}").json()
    assert detail["reopen_count"] == 2
    rounds = sorted({r["round_no"] for r in detail["rectifications"]})
    assert rounds == [1, 2, 3]
