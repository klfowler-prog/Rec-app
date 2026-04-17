import SwiftUI

struct ContentView: View {
    @State private var selectedTab = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            HomeView()
                .tabItem { Label("Home", systemImage: "house") }
                .tag(0)

            LibraryView()
                .tabItem { Label("Library", systemImage: "books.vertical") }
                .tag(1)

            TogetherView()
                .tabItem { Label("Together", systemImage: "person.2") }
                .tag(2)
        }
    }
}
