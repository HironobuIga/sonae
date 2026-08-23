from sonae.memory.store import HouseholdStore
from sonae.schemas import FamilyMember, Household


def make_household() -> Household:
    return Household(
        household_id="t1",
        address="長野県長野市穂保",
        lat=36.68,
        lon=138.27,
        muni_code="20201",
        muni_name="長野市",
        pref_name="長野県",
        jma_office_code="200000",
        jma_class20_code="2020111",
        members=[FamilyMember(name="Yoshiko", age=78)],
    )


def test_household_roundtrip(tmp_store):
    store = HouseholdStore("t1")
    store.save_household(make_household())
    loaded = store.load_household()
    assert loaded is not None
    assert loaded.members[0].name == "Yoshiko"
    assert HouseholdStore.list_households() == ["t1"]


def test_watch_state_and_journal(tmp_store):
    store = HouseholdStore("t1")
    watch = store.load_watch()
    assert watch.activated_level == 0
    watch.activated_level = 3
    watch.seen_event_keys.append("k1")
    store.save_watch(watch)
    store.log_event("test", {"a": 1})
    again = store.load_watch()
    assert again.activated_level == 3
    assert again.seen_event_keys == ["k1"]
    assert again.history[-1]["kind"] == "test"
