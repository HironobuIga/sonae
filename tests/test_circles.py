from sonae import circles
from sonae.memory.store import HouseholdStore
from sonae.schemas import CheckInStatus, Circle, FamilyMember, Household


def _mk_household(hid: str, members: list[str]) -> Household:
    return Household(
        household_id=hid,
        address=f"長野県長野市穂保 {hid}",
        lat=36.68,
        lon=138.27,
        muni_code="20201",
        muni_name="長野市",
        pref_name="長野県",
        jma_office_code="200000",
        members=[FamilyMember(name=m, age=80, needs=["mobility-limited"]) for m in members],
    )


def test_circle_roundtrip_and_board(tmp_store):
    for hid, members in (("h1", ["A", "B"]), ("h2", ["C"])):
        store = HouseholdStore(hid)
        store.save_household(_mk_household(hid, members))
    circle = Circle(circle_id="c1", name="Test Circle", coordinator="Chair", household_ids=["h1", "h2"])
    circles.save_circle(circle)
    assert circles.list_circles() == ["c1"]

    board = circles.circle_board(circles.load_circle("c1"))
    counts = circles.board_counts(board)
    assert counts["total"] == 3
    assert counts["pending"] == 3  # no check-ins yet -> roster fallback
    assert board[0]["members"][0]["needs"] == ["mobility-limited"]


def test_record_checkin_updates_board(tmp_store):
    store = HouseholdStore("h1")
    store.save_household(_mk_household("h1", ["A", "B"]))
    circles.record_checkin("h1", "A", "safe")
    circles.record_checkin("h1", "B", "needs_help", note="trapped upstairs")
    checkins = store.load_checkins()
    statuses = {c.member: c.status for c in checkins}
    assert statuses["A"] == CheckInStatus.safe
    assert statuses["B"] == CheckInStatus.needs_help
    assert [c.note for c in checkins if c.member == "B"] == ["trapped upstairs"]
    # journal captured both check-ins
    kinds = [h["kind"] for h in store.load_watch().history]
    assert kinds.count("checkin") == 2
