import AppKit
import Foundation
import Vision

guard CommandLine.arguments.count == 2 else {
    fatalError("Usage: swift tools/recognize_font.swift IMAGE")
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: imageURL),
      let bitmap = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fatalError("Cannot load image")
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = false
request.minimumTextHeight = 0.005
let handler = VNImageRequestHandler(cgImage: bitmap, options: [:])
try handler.perform([request])

var records: [[String: Any]] = []
for observation in request.results ?? [] {
    guard let candidate = observation.topCandidates(1).first else { continue }
    for index in candidate.string.indices {
        let end = candidate.string.index(after: index)
        guard let bounds = try candidate.boundingBox(for: index..<end) else { continue }
        let rectangle = bounds.boundingBox
        records.append([
            "text": String(candidate.string[index]),
            "confidence": candidate.confidence,
            "x": rectangle.midX * Double(bitmap.width),
            "y": (1 - rectangle.midY) * Double(bitmap.height)
        ])
    }
}
let data = try JSONSerialization.data(withJSONObject: records, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(data)