import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1 else {
    FileHandle.standardError.write("usage: ocr <image>\n".data(using: .utf8)!)
    exit(1)
}
let path = CommandLine.arguments[1]
guard let img = NSImage(contentsOfFile: path),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("cannot load image\n".data(using: .utf8)!)
    exit(1)
}
let request = VNRecognizeTextRequest { req, err in
    if let err = err {
        FileHandle.standardError.write("vision error: \(err)\n".data(using: .utf8)!)
        exit(1)
    }
    guard let results = req.results as? [VNRecognizedTextObservation] else {
        exit(1)
    }
    let lines = results.compactMap { $0.topCandidates(1).first?.string }
    print(lines.joined(separator: "\n"))
}
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["tr-TR", "en-US"]

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
try handler.perform([request])
