"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from openpilot.common.parameterized import parameterized

from openpilot.cereal import log, custom
from opendbc.car import structs
from openpilot.selfdrive.selfdrived.events import Events
from openpilot.sunnypilot.selfdrive.selfdrived.events import EventsSP
from openpilot.sunnypilot.mads.helpers import MadsSteeringModeOnBrake
from openpilot.sunnypilot.mads.mads import ModularAssistiveDrivingSystem
from openpilot.sunnypilot.selfdrive.car.car_specific import CarSpecificEventsSP
from openpilot.common.test import OpenpilotTestCase

State = custom.ModularAssistiveDrivingSystem.ModularAssistiveDrivingSystemState
EventName = log.OnroadEvent.EventName
EventNameSP = custom.OnroadEventSP.EventName
ButtonType = structs.CarState.ButtonEvent.Type
GearShifter = structs.CarState.GearShifter
SafetyModel = structs.CarParams.SafetyModel

UP_PRESS = ((ButtonType.cancel, True),)
UP_RELEASE = ((ButtonType.cancel, False),)
UP_2_PRESS = ((ButtonType.cancel, True), (ButtonType.altButton2, True))
UP_2_RELEASE = ((ButtonType.cancel, False), (ButtonType.altButton2, False))


def make_car_state(gear=GearShifter.drive, acc=False, buttons=(), brake_pressed=False, v_ego=10.0):
  cs = structs.CarState()
  cs.gearShifter = gear
  cs.cruiseState.enabled = acc
  cs.cruiseState.available = True
  cs.buttonEvents = [structs.CarState.ButtonEvent(type=t, pressed=p) for t, p in buttons]
  cs.brakePressed = brake_pressed
  cs.vEgo = v_ego
  cs.standstill = v_ego < 0.01
  return cs


def make_car_specific():
  CP = structs.CarParams()
  CP.brand = "rivian"
  return CarSpecificEventsSP(CP, structs.CarParamsSP())


def car_specific_step(car_specific, cs, event_names=()):
  events = Events()
  for name in event_names:
    events.add(name)
  events_sp = car_specific.update(cs, events)
  return events, events_sp


class TestRivianMadsExitEvents(OpenpilotTestCase):
  def test_up2_disengages_and_blocks_pcm_enable_while_held(self):
    car_specific = make_car_specific()

    events, events_sp = car_specific_step(car_specific, make_car_state(acc=True, buttons=UP_2_PRESS), [EventName.pcmEnable])
    assert events_sp.has(EventNameSP.lkasDisable)
    assert not events.has(EventName.pcmEnable)

    events, events_sp = car_specific_step(car_specific, make_car_state(), [EventName.pcmEnable])
    assert not events_sp.has(EventNameSP.lkasDisable)
    assert not events.has(EventName.pcmEnable)

    events, events_sp = car_specific_step(car_specific, make_car_state(buttons=UP_2_RELEASE), [EventName.pcmEnable])
    assert not events_sp.has(EventNameSP.lkasDisable)
    assert events.has(EventName.pcmEnable)

  def test_up_press_with_speed_control_off_disengages(self):
    _, events_sp = car_specific_step(make_car_specific(), make_car_state(acc=False, buttons=UP_PRESS))
    assert events_sp.has(EventNameSP.lkasDisable)

  def test_up_press_while_fully_engaged_only_cancels_speed_control(self):
    car_specific = make_car_specific()

    _, events_sp = car_specific_step(car_specific, make_car_state(acc=True, buttons=UP_PRESS))
    assert not events_sp.has(EventNameSP.lkasDisable)

    # still holding the stalk after the ACM drops ACC is the same press
    for _ in range(50):
      _, events_sp = car_specific_step(car_specific, make_car_state(acc=False))
      assert not events_sp.has(EventNameSP.lkasDisable)

    _, events_sp = car_specific_step(car_specific, make_car_state(acc=False, buttons=UP_RELEASE))
    assert not events_sp.has(EventNameSP.lkasDisable)

    # the next press starts with speed control off
    _, events_sp = car_specific_step(car_specific, make_car_state(acc=False, buttons=UP_PRESS))
    assert events_sp.has(EventNameSP.lkasDisable)

  @parameterized.expand([GearShifter.park, GearShifter.reverse], names=["gear"])
  def test_gear_entry_disengages_on_two_frames(self, gear):
    car_specific = make_car_specific()
    _, events_sp = car_specific_step(car_specific, make_car_state(v_ego=0.0))
    assert not events_sp.has(EventNameSP.lkasDisable)

    for _ in range(2):
      _, events_sp = car_specific_step(car_specific, make_car_state(gear=gear, v_ego=0.0))
      assert events_sp.has(EventNameSP.lkasDisable)

    _, events_sp = car_specific_step(car_specific, make_car_state(gear=gear, v_ego=0.0))
    assert not events_sp.has(EventNameSP.lkasDisable)

  def test_park_to_reverse_disengages_again(self):
    car_specific = make_car_specific()
    for _ in range(3):
      car_specific_step(car_specific, make_car_state(gear=GearShifter.park, v_ego=0.0))
    _, events_sp = car_specific_step(car_specific, make_car_state(gear=GearShifter.reverse, v_ego=0.0))
    assert events_sp.has(EventNameSP.lkasDisable)

  def test_pcm_enable_blocked_in_park(self):
    events, _ = car_specific_step(make_car_specific(), make_car_state(gear=GearShifter.park, v_ego=0.0), [EventName.pcmEnable])
    assert not events.has(EventName.pcmEnable)

  def test_driving_with_brake_adds_nothing(self):
    car_specific = make_car_specific()
    for acc in (True, False):
      events, events_sp = car_specific_step(car_specific, make_car_state(acc=acc, brake_pressed=True), [EventName.pcmEnable])
      assert not events_sp.has(EventNameSP.lkasDisable)
      assert events.has(EventName.pcmEnable)


# end to end through the MADS state machine, with the brake mode read from the param as on the car

def make_panda_state(mocker):
  ps = mocker.MagicMock()
  ps.controlsAllowedLateral = True
  ps.safetyModel = SafetyModel.rivian
  return ps


def make_rivian_mads(mocker, steering_mode=MadsSteeringModeOnBrake.REMAIN_ACTIVE):
  sd = mocker.MagicMock()
  sd.CP = structs.CarParams()
  sd.CP.brand = "rivian"
  sd.CP_SP = structs.CarParamsSP()
  sd.params = mocker.MagicMock()
  sd.params.get_bool = mocker.MagicMock(side_effect=lambda k: {
    "Mads": True, "MadsMainCruiseAllowed": False,
    "DisengageOnAccelerator": False, "MadsUnifiedEngagementMode": True,
  }.get(k, False))
  sd.params.get = mocker.MagicMock(return_value=steering_mode)
  sd.events = Events()
  sd.events_sp = EventsSP()
  sd.enabled = False
  sd.enabled_prev = False
  sd.initialized = True
  sd.CS_prev = make_car_state()
  sd.sm = {'pandaStates': [make_panda_state(mocker)]}
  sd.state_machine = mocker.MagicMock()

  mads = ModularAssistiveDrivingSystem(sd)
  mads.state_machine.state = State.enabled
  mads.enabled = True
  mads.active = True
  return mads, sd


def run_frame(car_specific, mads, sd, cs, event_names=(), selfdrive_enabled=False):
  # same order as selfdrived: car events, car specific events, then MADS
  sd.enabled = selfdrive_enabled
  for name in event_names:
    sd.events.add(name)
  sd.events_sp.add_from_msg(car_specific.update(cs, sd.events).to_msg())
  mads.update(cs)
  sd.CS_prev = cs
  sd.events.clear()
  sd.events_sp.clear()


class TestRivianMadsExits(OpenpilotTestCase):
  def test_brake_keeps_steering_in_remain_active(self, mocker):
    mads, sd = make_rivian_mads(mocker)
    assert mads.steering_mode_on_brake == MadsSteeringModeOnBrake.REMAIN_ACTIVE
    car_specific = make_car_specific()

    run_frame(car_specific, mads, sd, make_car_state(acc=False, brake_pressed=True), [EventName.pedalPressed, EventName.pcmDisable])
    for _ in range(100):
      run_frame(car_specific, mads, sd, make_car_state(acc=False, brake_pressed=True, v_ego=0.0), [EventName.pcmDisable])
    assert mads.state_machine.state == State.enabled

  def test_brake_still_disengages_in_disengage_mode(self, mocker):
    mads, sd = make_rivian_mads(mocker, MadsSteeringModeOnBrake.DISENGAGE)
    run_frame(make_car_specific(), mads, sd, make_car_state(acc=False, brake_pressed=True), [EventName.pedalPressed])
    assert mads.state_machine.state == State.disabled

  def test_up_press_after_speed_control_off_ends_steering(self, mocker):
    mads, sd = make_rivian_mads(mocker)
    run_frame(make_car_specific(), mads, sd, make_car_state(acc=False, buttons=UP_PRESS), [EventName.pcmDisable])
    assert mads.state_machine.state == State.disabled

  def test_one_up_press_never_ends_both(self, mocker):
    mads, sd = make_rivian_mads(mocker)
    car_specific = make_car_specific()

    # fully engaged: the press cancels speed control (natively and through buttonCancel), steering stays
    run_frame(car_specific, mads, sd, make_car_state(acc=True, buttons=UP_PRESS), [EventName.buttonCancel], selfdrive_enabled=True)
    for _ in range(20):
      run_frame(car_specific, mads, sd, make_car_state(acc=False), [EventName.pcmDisable])
    run_frame(car_specific, mads, sd, make_car_state(acc=False, buttons=UP_RELEASE), [EventName.pcmDisable, EventName.buttonCancel])
    assert mads.state_machine.state == State.enabled

    # a second press ends steering
    run_frame(car_specific, mads, sd, make_car_state(acc=False, buttons=UP_PRESS), [EventName.pcmDisable, EventName.buttonCancel])
    assert mads.state_machine.state == State.disabled

  def test_up2_ends_everything(self, mocker):
    mads, sd = make_rivian_mads(mocker)
    run_frame(make_car_specific(), mads, sd, make_car_state(acc=True, buttons=UP_2_PRESS), [EventName.buttonCancel], selfdrive_enabled=True)
    assert mads.state_machine.state == State.disabled

  @parameterized.expand([(GearShifter.park, (EventName.wrongGear,)),
                         (GearShifter.reverse, (EventName.wrongGear, EventName.reverseGear))], names=["gear", "gear_events"])
  def test_gear_entry_ends_steering_instead_of_pausing(self, mocker, gear, gear_events):
    mads, sd = make_rivian_mads(mocker)
    car_specific = make_car_specific()
    run_frame(car_specific, mads, sd, make_car_state(acc=False, brake_pressed=True, v_ego=0.0), [EventName.pcmDisable])

    for _ in range(10):
      run_frame(car_specific, mads, sd, make_car_state(gear=gear, acc=False, brake_pressed=True, v_ego=0.0),
                [EventName.pcmDisable, *gear_events])
    assert mads.state_machine.state == State.disabled

    # shifting back to drive does not bring steering back
    run_frame(car_specific, mads, sd, make_car_state(acc=False, v_ego=0.0), [EventName.pcmDisable])
    assert mads.state_machine.state == State.disabled
