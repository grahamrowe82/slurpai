// audio_setup.swift — Creates a persistent Multi-Output Device for SlurpAI.
//
// Combines Built-in Output + BlackHole 2ch into a single Multi-Output Device
// that survives reboots (kAudioAggregateDeviceIsPrivateKey = 0).
//
// Compile: swiftc -O -o audio_setup audio_setup.swift -framework CoreAudio -framework AudioToolbox
// Run:     ./audio_setup

import CoreAudio
import Foundation

let deviceUID = "com.slurpai.multi-output"
let deviceName = "SlurpAI Multi-Output"

// MARK: - Device enumeration

func getAllDeviceIDs() -> [AudioDeviceID] {
    var size: UInt32 = 0
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDevices,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size) == noErr else {
        return []
    }
    let count = Int(size) / MemoryLayout<AudioDeviceID>.size
    var devices = [AudioDeviceID](repeating: 0, count: count)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &devices) == noErr else {
        return []
    }
    return devices
}

func getStringProperty(_ deviceID: AudioDeviceID, selector: AudioObjectPropertySelector) -> String? {
    var size: UInt32 = 0
    var address = AudioObjectPropertyAddress(
        mSelector: selector,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
    guard AudioObjectGetPropertyDataSize(deviceID, &address, 0, nil, &size) == noErr else {
        return nil
    }
    var value: Unmanaged<CFString>?
    guard AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, &value) == noErr,
          let cf = value?.takeUnretainedValue() else {
        return nil
    }
    return cf as String
}

func getDeviceName(_ deviceID: AudioDeviceID) -> String? {
    getStringProperty(deviceID, selector: kAudioObjectPropertyName)
}

func getDeviceUID(_ deviceID: AudioDeviceID) -> String? {
    getStringProperty(deviceID, selector: kAudioDevicePropertyDeviceUID)
}

func findDeviceUID(nameMatching candidates: [String]) -> String? {
    for deviceID in getAllDeviceIDs() {
        guard let name = getDeviceName(deviceID) else { continue }
        if candidates.contains(name) {
            return getDeviceUID(deviceID)
        }
    }
    return nil
}

// MARK: - Check if device already exists

func deviceAlreadyExists() -> Bool {
    for deviceID in getAllDeviceIDs() {
        if let uid = getDeviceUID(deviceID), uid == deviceUID {
            return true
        }
    }
    return false
}

// MARK: - Main

if deviceAlreadyExists() {
    print("SlurpAI Multi-Output device already exists.")
    exit(0)
}

// Find Built-in Output (name varies by Mac model)
guard let builtInUID = findDeviceUID(nameMatching: ["Built-in Output", "MacBook Pro Speakers", "MacBook Air Speakers", "External Headphones"]) else {
    fputs("Error: Could not find Built-in Output device.\n", stderr)
    fputs("Available devices:\n", stderr)
    for deviceID in getAllDeviceIDs() {
        if let name = getDeviceName(deviceID), let uid = getDeviceUID(deviceID) {
            fputs("  \(name) (\(uid))\n", stderr)
        }
    }
    exit(1)
}

guard let blackholeUID = findDeviceUID(nameMatching: ["BlackHole 2ch"]) else {
    fputs("Error: BlackHole 2ch not found.\n", stderr)
    fputs("Install it: brew install --cask blackhole-2ch\n", stderr)
    exit(1)
}

// Create the aggregate device
let desc: [String: Any] = [
    kAudioAggregateDeviceUIDKey as String: deviceUID,
    kAudioAggregateDeviceNameKey as String: deviceName,
    kAudioAggregateDeviceIsPrivateKey as String: 0,    // public = persistent
    kAudioAggregateDeviceIsStackedKey as String: 0,     // multi-output behaviour
    kAudioAggregateDeviceSubDeviceListKey as String: [
        [kAudioSubDeviceUIDKey as String: builtInUID],
        [kAudioSubDeviceUIDKey as String: blackholeUID],
    ],
    kAudioAggregateDeviceMainSubDeviceKey as String: builtInUID,
]

var aggregateID: AudioDeviceID = 0
let status = AudioHardwareCreateAggregateDevice(desc as CFDictionary, &aggregateID)

guard status == noErr else {
    fputs("Error: Failed to create aggregate device (OSStatus \(status)).\n", stderr)
    exit(1)
}

// Give CoreAudio a moment to register the new device
CFRunLoopRunInMode(.defaultMode, 0.5, false)

print("Created \(deviceName) (device ID: \(aggregateID))")
exit(0)
