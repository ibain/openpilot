"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from openpilot.cereal import log, custom
from opendbc.car import structs

from opendbc.car.chrysler.values import RAM_DT
from openpilot.selfdrive.selfdrived.events import Events
from openpilot.sunnypilot.selfdrive.selfdrived.events import EventsSP

EventName = log.OnroadEvent.EventName
EventNameSP = custom.OnroadEventSP.EventName
ButtonType = structs.CarState.ButtonEvent.Type
GearShifter = structs.CarState.GearShifter

RIVIAN_MADS_EXIT_GEARS = (GearShifter.park, GearShifter.reverse)


class CarSpecificEventsSP:
  def __init__(self, CP: structs.CarParams, CP_SP: structs.CarParamsSP):
    self.CP = CP
    self.CP_SP = CP_SP

    self.low_speed_alert = False
    self.rivian_stalk_up2 = False
    self.rivian_prev_gear = GearShifter.unknown
    self.rivian_gear_exit_frames = 0

  def update(self, CS: structs.CarState, events: Events):
    events_sp = EventsSP()

    if self.CP.brand == 'chrysler':
      if self.CP.carFingerprint in RAM_DT:
        # remove belowSteerSpeed event from CarSpecificEvents as RAM_DT uses a different logic
        if events.has(EventName.belowSteerSpeed):
          events.remove(EventName.belowSteerSpeed)

        # TODO-SP: use if/elif to have the gear shifter condition takes precedence over the speed condition
        # TODO-SP: add 1 m/s hysteresis
        if CS.vEgo >= self.CP.minEnableSpeed:
          self.low_speed_alert = False
        if self.CP.minEnableSpeed >= 14.5 and CS.gearShifter != GearShifter.drive:
          self.low_speed_alert = True
      if self.low_speed_alert:
        events.add(EventName.belowSteerSpeed)

    elif self.CP.brand == 'toyota':
      if self.CP.openpilotLongitudinalControl:
        if CS.cruiseState.standstill and not CS.brakePressed and self.CP_SP.enableGasInterceptor:
          if events.has(EventName.resumeRequired):
            events.remove(EventName.resumeRequired)

    elif self.CP.brand == 'rivian':
      # Rivian has no MADS button, so the stalk and the gear selector end MADS steering fully (not pause)
      for be in CS.buttonEvents:
        if be.type == ButtonType.altButton2:
          # stalk UP_2 (past the detent) ends everything
          self.rivian_stalk_up2 = be.pressed
          if be.pressed:
            events_sp.add(EventNameSP.lkasDisable)
        elif be.type == ButtonType.cancel and be.pressed and not CS.cruiseState.enabled:
          # a new stalk up press that starts with speed control already off ends steering. One press while
          # fully engaged only cancels speed control natively, and holding it through that cancel is not a new press
          events_sp.add(EventNameSP.lkasDisable)

      # Shifting into park or reverse ends steering. On the shift frame mads.update_events() also adds
      # silentLkasDisable for wrongGear/reverseGear, which wins and pauses MADS, so send lkasDisable
      # again on the next frame, when it alone takes MADS from paused to disabled.
      if CS.gearShifter in RIVIAN_MADS_EXIT_GEARS:
        if CS.gearShifter != self.rivian_prev_gear:
          self.rivian_gear_exit_frames = 2
      else:
        self.rivian_gear_exit_frames = 0
      if self.rivian_gear_exit_frames > 0:
        events_sp.add(EventNameSP.lkasDisable)
        self.rivian_gear_exit_frames -= 1
      self.rivian_prev_gear = CS.gearShifter

      # no engagement while the stalk is held past the detent or in park
      if self.rivian_stalk_up2 or CS.gearShifter == GearShifter.park:
        events.remove(EventName.pcmEnable)

    return events_sp
