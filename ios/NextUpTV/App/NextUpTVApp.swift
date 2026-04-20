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
            // NAVY THEME — applied once at the app root.
            .preferredColorScheme(.dark)
            .tint(Theme.gold)
            .foregroundStyle(Theme.ink)
            .background(Theme.bg.ignoresSafeArea())
        }
    }
}
