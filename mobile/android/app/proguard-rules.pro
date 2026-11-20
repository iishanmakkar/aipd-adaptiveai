# Add project specific ProGuard rules here.
# By default, the flags in this file are appended to flags specified
# in /usr/local/Cellar/android-sdk/24.3.3/tools/proguard/proguard-android.txt
# You can edit the include path and order by changing the proguardFiles
# directive in build.gradle.
#
# For more details, see
#   http://developer.android.com/guide/developing/tools/proguard.html

# react-native-reanimated
-keep class com.swmansion.reanimated.** { *; }
-keep class com.facebook.react.turbomodule.** { *; }

# JNI entry points are referenced by mangled name from C++ — R8 must not rename them.
-keep class com.adaptiveai.mobile.assist.LocalLlmNative { *; }
-keep class com.adaptiveai.mobile.assist.LocalLlmModule { *; }
-keep class com.adaptiveai.mobile.assist.AdaptiveModule { *; }
-keep class com.adaptiveai.mobile.assist.AdaptiveAccessibilityService { *; }
-keep class com.adaptiveai.mobile.assist.CaptureService { *; }
-keep class com.adaptiveai.mobile.assist.AssistForegroundService { *; }

# Add any project specific keep options here:
