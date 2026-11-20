#!/usr/bin/env bash
# Expo SDK 51 (React Native 0.74) predates compileSdk 35+. With compileSdk 35/36/37
# (Android 15/16/17) the expo-modules-core module fails to compile:
#
#   PermissionsService.kt:166:36 Only safe (?.) or non-null asserted (!!.) calls
#   are allowed on a nullable receiver of type Array<(out) String!>?
#
# The SDK 35+ stubs type PackageInfo.requestedPermissions as nullable, so the old
# `requestedPermissions?.contains(...)` call shape no longer compiles. This patch
# rewrites it to a null-safe asList() check that compiles on 34, 35, 36 and 37.
#
# Run after every `npm install` and BEFORE building with compileSdk >= 35.
# Proper long-term fix: upgrade Expo to SDK 53+ (React Native 0.79+, 16 KB aligned).
set -e
TARGET="node_modules/expo-modules-core/android/src/main/java/expo/modules/adapters/react/permissions/PermissionsService.kt"
if [ ! -f "$TARGET" ]; then
  echo "Patch target not found (node_modules not installed?). Skipping."
  exit 0
fi
if grep -q 'requestedPermissions?.asList()?.contains' "$TARGET"; then
  echo "Already patched."
  exit 0
fi
if grep -q 'requestedPermissions?.contains' "$TARGET"; then
  perl -pi -e 's/requestedPermissions\?\.\contains/requestedPermissions?.asList()?.contains/g' "$TARGET"
  echo "Patched $TARGET for compileSdk 35+."
  exit 0
fi
echo "Pattern not found — expo-modules-core may already be SDK35-safe. Skipping."
exit 0
