import unittest

from opendbc.car import Bus, structs
from opendbc.sunnypilot.car.rivian.carstate_ext import CarStateExt
from opendbc.sunnypilot.car.rivian.values import RivianFlagsSP

ButtonType = structs.CarState.ButtonEvent.Type

IDLE, UP_1, UP_2, DOWN_1 = 0, 1, 2, 3


class FakeParser:
  def __init__(self):
    self.vl = {
      "VDM_AdasSts": {"VDM_UserAdasRequest": IDLE},
      "WheelButtons_Fwd": {"RightButton_Scroll": 0, "RightButton_RightClick": 0, "RightButton_LeftClick": 0},
      "Cluster": {"Cluster_Unit": 1},
    }


class TestRivianStalk(unittest.TestCase):
  def setUp(self):
    CP = structs.CarParams()
    CP.brand = "rivian"
    self.cs = CarStateExt(CP, structs.CarParamsSP())
    self.parser = FakeParser()

  def _stalk(self, position):
    self.parser.vl["VDM_AdasSts"]["VDM_UserAdasRequest"] = position
    return [(be.type, be.pressed) for be in self.cs.update_stalk({Bus.pt: self.parser})]

  def test_stalk_positions(self):
    steps = [
      (UP_1, [(ButtonType.cancel, True)]),
      (UP_1, []),
      # UP_1 to UP_2 and back is the same held press, so no new cancel press
      (UP_2, [(ButtonType.altButton2, True)]),
      (UP_2, []),
      (UP_1, [(ButtonType.altButton2, False)]),
      (IDLE, [(ButtonType.cancel, False)]),
      # a flick straight to UP_2 in one frame
      (UP_2, [(ButtonType.cancel, True), (ButtonType.altButton2, True)]),
      (IDLE, [(ButtonType.cancel, False), (ButtonType.altButton2, False)]),
      (DOWN_1, []),
      (UP_1, [(ButtonType.cancel, True)]),
    ]
    for position, expected in steps:
      with self.subTest(position=position):
        self.assertEqual(self._stalk(position), expected)

  def test_stalk_and_distance_events_in_one_frame(self):
    CP = structs.CarParams()
    CP.brand = "rivian"
    CP.openpilotLongitudinalControl = True
    CP_SP = structs.CarParamsSP()
    CP_SP.flags = RivianFlagsSP.LONGITUDINAL_HARNESS_UPGRADE.value
    cs = CarStateExt(CP, CP_SP)
    parsers = {Bus.pt: self.parser, Bus.adas: self.parser, Bus.alt: self.parser}

    self.parser.vl["WheelButtons_Fwd"]["RightButton_Scroll"] = 1
    self.parser.vl["VDM_AdasSts"]["VDM_UserAdasRequest"] = UP_2
    ret = structs.CarState()
    cs.update(ret, parsers)
    self.assertEqual([(be.type, be.pressed) for be in ret.buttonEvents],
                     [(ButtonType.gapAdjustCruise, False), (ButtonType.cancel, True), (ButtonType.altButton2, True)])


if __name__ == "__main__":
  unittest.main()
