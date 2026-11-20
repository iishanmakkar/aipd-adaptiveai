// Route types for expo-router. The typedRoutes generator (expo-router 3.5) mangles Windows
// paths — it emits backslash routes like `/(tabs)\tools` and treats files outside app/ as
// routes — so typedRoutes is disabled in app.json and this committed file is the stable
// source of href types. Keep it in sync when tabs are added or renamed.
declare module 'expo-router' {
  export namespace ExpoRouter {
    export interface __routes<T extends string = string> extends Record<string, unknown> {
      StaticRoutes:
        | `/`
        | `/(tabs)`
        | `/(tabs)/`
        | `/(tabs)/screen`
        | `/(tabs)/settings`
        | `/(tabs)/tasks`
        | `/(tabs)/tools`
        | `/(tabs)/shopping`
        | `/screen`
        | `/settings`
        | `/tasks`
        | `/tools`
        | `/shopping`
        | `/_sitemap`;
      DynamicRoutes: never;
      DynamicRouteTemplate: never;
    }
  }
}
