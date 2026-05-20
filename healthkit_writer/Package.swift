// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "healthkit-writer",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "healthkit-writer",
            path: "Sources/healthkit_writer"
        ),
    ]
)
