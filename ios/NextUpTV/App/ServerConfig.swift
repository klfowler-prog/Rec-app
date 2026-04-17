import Foundation

enum ServerConfig {
    #if DEBUG
    static let baseURL = URL(string: "http://192.168.0.41:8000")!
    #else
    static let baseURL = URL(string: "https://nextup-493018.run.app")!
    #endif
}
