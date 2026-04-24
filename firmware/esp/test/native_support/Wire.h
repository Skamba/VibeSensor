#pragma once

class TwoWire {
 public:
  void begin(int = 0, int = 0) {}
  void setClock(unsigned long) {}
};

static TwoWire Wire;
