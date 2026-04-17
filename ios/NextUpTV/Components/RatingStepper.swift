import SwiftUI

struct RatingStepper: View {
    @Binding var value: Double
    var range: ClosedRange<Double> = 1...10
    var step: Double = 1

    var body: some View {
        HStack(spacing: 24) {
            Button {
                if value > range.lowerBound { value -= step }
            } label: {
                Image(systemName: "minus.circle.fill")
                    .font(.title)
            }
            .disabled(value <= range.lowerBound)

            Text("\(value, specifier: "%.0f")")
                .font(.system(size: 72, weight: .bold, design: .rounded))
                .frame(minWidth: 100)

            Button {
                if value < range.upperBound { value += step }
            } label: {
                Image(systemName: "plus.circle.fill")
                    .font(.title)
            }
            .disabled(value >= range.upperBound)
        }

        HStack(spacing: 4) {
            ForEach(1...10, id: \.self) { i in
                Image(systemName: Double(i) <= value ? "star.fill" : "star")
                    .font(.caption)
                    .foregroundStyle(Double(i) <= value ? Color.yellow : Color.gray.opacity(0.3))
            }
        }
    }
}
