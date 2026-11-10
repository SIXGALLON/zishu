// 用 macOS Vision 抠出照片里的主体（人、物），输出灰度蒙版 <stem>_mask.png
// 用法：swift lift.swift <照片目录> <输出目录>
// 需要 macOS 14+。识别不到主体的照片会打印 "no subject"，引擎会自动避开需要抠图的手法。
import Foundation
import Vision
import CoreImage
import AppKit

let args = CommandLine.arguments
guard args.count >= 3 else { print("usage: swift lift.swift <images> <out>"); exit(1) }
let dir = URL(fileURLWithPath: args[1])
let out = URL(fileURLWithPath: args[2])
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
let ctx = CIContext()
let exts: Set<String> = ["jpg", "jpeg", "png", "webp", "heic"]
let files = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
for url in files.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) where exts.contains(url.pathExtension.lowercased()) {
  let stem = url.deletingPathExtension().lastPathComponent
  let dst = out.appendingPathComponent(stem + "_mask.png")
  if FileManager.default.fileExists(atPath: out.appendingPathComponent(stem + "_info.json").path) { print(stem, "cached"); continue }
  guard let ci = CIImage(contentsOf: url, options: [.applyOrientationProperty: true]) else { print(stem, "noimg"); continue }
  let h = VNImageRequestHandler(ciImage: ci)
  let r = VNGenerateForegroundInstanceMaskRequest()
  let hr = VNDetectHumanRectanglesRequest()
  hr.upperBodyOnly = false
  do {
    try h.perform([r, hr])
    let humans = hr.results?.count ?? 0
    let info = "{\"humans\": \(humans)}"
    try? info.write(to: out.appendingPathComponent(stem + "_info.json"), atomically: true, encoding: .utf8)
    guard let res = r.results?.first else { print(stem, "no subject"); continue }
    let buf = try res.generateScaledMaskForImage(forInstances: res.allInstances, from: h)
    let mask = CIImage(cvPixelBuffer: buf)
    guard let cg = ctx.createCGImage(mask, from: mask.extent) else { continue }
    let rep = NSBitmapImageRep(cgImage: cg)
    try rep.representation(using: .png, properties: [:])!.write(to: dst)
    print(stem, "instances", res.allInstances.count)
  } catch { print(stem, "err", error) }
}
