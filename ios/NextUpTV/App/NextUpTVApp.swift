import SwiftUI

@main
struct NextUpTVApp: App {
    @StateObject private var authStore = AuthStore()

    var body: some Scene {
        WindowGroup {
            Group {
                switch authStore.state {
                case .unknown:
                    ProgressView()
                case .unauthenticated:
                    DevicePairingView()
                case .authenticated:
                    ContentView()
                }
            }
            .environmentObject(authStore)
            .environmentObject(APIClient(authStore: authStore))
        }
    }
}
