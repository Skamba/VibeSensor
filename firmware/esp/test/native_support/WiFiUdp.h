#pragma once

#include <cstdint>
#include <deque>
#include <initializer_list>
#include <vector>

#include "Arduino.h"

class WiFiUDP {
 public:
  struct SentPacket {
    IPAddress ip;
    uint16_t port = 0;
    std::vector<uint8_t> payload;
  };

  int begin(uint16_t port) {
    begin_port = port;
    return 1;
  }

  void reset() {
    begin_port = 0;
    sent_packets.clear();
    incoming_packets_.clear();
    begin_packet_results_.clear();
    end_packet_results_.clear();
    active_payload_.clear();
    packet_open_ = false;
  }

  void setBeginPacketResults(std::initializer_list<int> results) {
    begin_packet_results_ = std::deque<int>(results.begin(), results.end());
  }

  void setEndPacketResults(std::initializer_list<int> results) {
    end_packet_results_ = std::deque<int>(results.begin(), results.end());
  }

  int beginPacket(const IPAddress& ip, uint16_t port) {
    active_ip_ = ip;
    active_port_ = port;
    active_payload_.clear();
    const int result = begin_packet_results_.empty() ? 1 : begin_packet_results_.front();
    if (!begin_packet_results_.empty()) {
      begin_packet_results_.pop_front();
    }
    packet_open_ = (result == 1);
    return result;
  }

  size_t write(const uint8_t* data, size_t len) {
    if (!packet_open_) {
      return 0;
    }
    active_payload_.insert(active_payload_.end(), data, data + len);
    return len;
  }

  int endPacket() {
    const int result = end_packet_results_.empty() ? 1 : end_packet_results_.front();
    if (!end_packet_results_.empty()) {
      end_packet_results_.pop_front();
    }
    if (packet_open_ && result == 1) {
      SentPacket packet;
      packet.ip = active_ip_;
      packet.port = active_port_;
      packet.payload = active_payload_;
      sent_packets.push_back(packet);
    }
    packet_open_ = false;
    active_payload_.clear();
    return result;
  }

  void queueIncoming(const uint8_t* data, size_t len) {
    incoming_packets_.push_back(std::vector<uint8_t>(data, data + len));
  }

  int parsePacket() { return incoming_packets_.empty() ? 0 : incoming_packets_.front().size(); }

  int read(uint8_t* buffer, size_t len) {
    if (incoming_packets_.empty()) {
      return 0;
    }
    const std::vector<uint8_t>& packet = incoming_packets_.front();
    const size_t to_copy = packet.size() < len ? packet.size() : len;
    for (size_t i = 0; i < to_copy; ++i) {
      buffer[i] = packet[i];
    }
    incoming_packets_.pop_front();
    return static_cast<int>(to_copy);
  }

  uint16_t begin_port = 0;
  std::vector<SentPacket> sent_packets;

 private:
  std::deque<std::vector<uint8_t>> incoming_packets_;
  std::deque<int> begin_packet_results_;
  std::deque<int> end_packet_results_;
  IPAddress active_ip_;
  uint16_t active_port_ = 0;
  std::vector<uint8_t> active_payload_;
  bool packet_open_ = false;
};
