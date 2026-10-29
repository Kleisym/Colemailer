# minifyEnabled сейчас выключен, но правила держим на случай включения:
# Chaquopy дергает Kotlin-классы рефлексией по имени метода.
-keep class com.chaquo.python.** { *; }
-keep class com.colemailer.app.BotCallback { *; }
-keepclassmembers class com.colemailer.app.BotCallback {
    public *;
}
-dontwarn com.chaquo.python.**

# Python-зависимости ставятся pip'ом, Java-часть не минифицируется.
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn org.slf4j.**
