import SwiftUI

struct SignalView: View {
    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Image(systemName: "waveform.path")
                    .font(.system(size: 64))
                    .foregroundStyle(Theme.gold)
                Text("My Signal")
                    .font(.system(size: Theme.FontSize.rowTitle, weight: .bold))
                    .foregroundStyle(Theme.ink)
                Text("Your taste profile and signal strength will appear here.")
                    .font(.system(size: Theme.FontSize.body))
                    .foregroundStyle(Theme.inkDim)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 500)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Theme.bg)
            .navigationTitle("My Signal")
        }
    }
}
