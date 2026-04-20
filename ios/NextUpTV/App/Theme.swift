import SwiftUI

/// NextUp · Navy theme palette.
/// Matches the `tv.*` namespace in the web app's Tailwind config so that
/// web + tvOS share the same visual language.
enum Theme {
    // Base surfaces
    static let bg       = Color(hex: 0x1E2A3A) // navy-dark
    static let surface  = Color(hex: 0x2B3A4E) // navy
    static let surface2 = Color(hex: 0x3D5068) // navy-light

    // Text
    static let ink      = Color(hex: 0xF5F0E8) // cream
    static let inkDim   = Color(hex: 0xF5F0E8).opacity(0.72)
    static let inkFaint = Color(hex: 0xF5F0E8).opacity(0.50)
    static let line     = Color(hex: 0xF5F0E8).opacity(0.12)

    // Accents
    static let gold = Color(hex: 0xB8A97E) // primary action / signal
    static let sage = Color(hex: 0xA8B88A) // focus halo / secondary
    static let coral = Color(hex: 0xF09A7A) // destructive / "Noise"

    // Type scale — tvOS 10-foot reading distance
    enum FontSize {
        static let eyebrow: CGFloat = 22
        static let body: CGFloat    = 28
        static let rowTitle: CGFloat = 40
        static let heroTitle: CGFloat = 88
        static let detailTitle: CGFloat = 104
    }

    // Spacing
    enum Spacing {
        static let screenPadding: CGFloat = 60
        static let rowGap: CGFloat        = 48
        static let posterGap: CGFloat     = 28
    }
}

extension Color {
    /// Build a Color from a 0xRRGGBB hex literal.
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red:   Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >>  8) & 0xFF) / 255,
            blue:  Double( hex        & 0xFF) / 255,
            opacity: 1
        )
    }
}

/// Reusable eyebrow label — small uppercase gold text above titles.
struct Eyebrow: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.system(size: Theme.FontSize.eyebrow, weight: .semibold))
            .tracking(2.5)
            .textCase(.uppercase)
            .foregroundStyle(Theme.gold)
    }
}

/// Signal score pill — the "8.9" chip shown on posters + hero.
struct SignalBadge: View {
    let value: Double
    var size: Size = .regular

    enum Size { case small, regular, large }

    private var fontSize: CGFloat {
        switch size { case .small: return 14; case .regular: return 18; case .large: return 28 }
    }
    private var padH: CGFloat {
        switch size { case .small: return 8; case .regular: return 12; case .large: return 18 }
    }
    private var padV: CGFloat {
        switch size { case .small: return 4; case .regular: return 6; case .large: return 10 }
    }

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "waveform.path")
                .font(.system(size: fontSize * 0.75, weight: .bold))
            Text(String(format: "%.1f", value))
                .font(.system(size: fontSize, weight: .semibold).monospacedDigit())
        }
        .foregroundStyle(Theme.gold)
        .padding(.horizontal, padH)
        .padding(.vertical, padV)
        .background(Theme.surface.opacity(0.85), in: Capsule())
        .overlay(
            Capsule().stroke(Theme.gold.opacity(0.3), lineWidth: 1)
        )
    }
}
