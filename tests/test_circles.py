from sonae import circles
from sonae.memory.store import HouseholdStore
from sonae.schemas import CheckIn, CheckInStatus, Circle, FamilyMember, Household


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


def test_remote_members_are_phone_followups_not_door_knocks(tmp_store):
    """Nobody walks to the door of a son who lives in another city."""
    store = HouseholdStore("h1")
    household = _mk_household("h1", ["Yoshiko"])
    household.members.append(FamilyMember(name="Kenji", age=52, lives_at_home=False))
    store.save_household(household)
    circle = Circle(circle_id="c1", name="Test Circle", coordinator="Chair", household_ids=["h1"])
    circles.save_circle(circle)

    board = circles.circle_board(circle)
    assert [m["lives_at_home"] for m in board[0]["members"]] == [True, False]
    counts = circles.board_counts(board)
    assert counts["total"] == 1 and counts["pending"] == 1  # only the member who is home
    assert counts["remote"] == 1
    assert circles.phone_followups(board) == ["h1/Kenji"]

    # a remote member answering the phone must not change the door-knock board
    store.save_checkins([CheckIn(member="Yoshiko"), CheckIn(member="Kenji")])
    circles.record_checkin("h1", "Kenji", "safe")
    counts = circles.board_counts(circles.circle_board(circle))
    assert counts["pending"] == 1 and counts["safe"] == 0
    assert counts["remote"] == 1
    assert circles.phone_followups(circles.circle_board(circle)) == []


def test_circle_journal_records_failures(tmp_store):
    circles.log_circle_event("c1", "error", {"op": "coordinator_report", "error": "model timeout"})
    journal = circles.circle_journal("c1")
    assert journal[-1]["kind"] == "error" and journal[-1]["op"] == "coordinator_report"
    # the journal sidecar is not a circle definition
    assert circles.list_circles() == []


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
