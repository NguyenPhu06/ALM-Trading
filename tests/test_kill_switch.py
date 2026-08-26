from paper import GlobalKillSwitch,PaperRiskEngine
def test_kill_switch_blocks_entry_but_permits_safe_management():
    switch=GlobalKillSwitch();switch.activate();engine=PaperRiskEngine(kill_switch=switch)
    assert not engine.evaluate(new_entry=True).allowed and engine.evaluate(new_entry=False).allowed
