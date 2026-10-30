plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.hilt)
    alias(libs.plugins.ksp)
    alias(libs.plugins.detekt)
}

// 长期发布签名。历史坑: release.yml 曾跑 assembleDebug, CI 临时 runner 每次新生成
// 一把 debug.keystore, 在役 7 个包实测 5 种证书 => 手机装更新包报
// 「更新包与已安装应用的签名不一致」。凭据只在用户级 gradle.properties / Actions
// env 里, 不进仓库任何 tracked 文件。
val releaseSecret: (String) -> String? = { key ->
    providers.gradleProperty(key).orNull?.takeIf { it.isNotBlank() }
        ?: providers.environmentVariable(key).orNull?.takeIf { it.isNotBlank() }
}

val releaseStoreFile = releaseSecret("RELEASE_STORE_FILE")

// 只在真要出 release 产物时把关: CI 的 ktlint/detekt/testDebugUnitTest/assembleDebug
// 都不该被缺凭据拖红 (.github/workflows/android-ci.yml)。
val releaseRequested = gradle.startParameter.taskNames.any {
    it.contains("Release", ignoreCase = true) || it in setOf("build", "assemble", "bundle")
}
if (releaseRequested && releaseStoreFile == null) {
    throw GradleException(
        "缺少 RELEASE_STORE_FILE (另需 RELEASE_STORE_PASSWORD / RELEASE_KEY_ALIAS / " +
            "RELEASE_KEY_PASSWORD)。本地写进 ~/.gradle/gradle.properties, CI 配 GitHub " +
            "Actions Secrets, 见 docs/operations.md §3.1。不许退回 assembleDebug 出 OTA 包。"
    )
}

android {
    namespace = "com.app.english"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.app.english"
        minSdk = 26
        targetSdk = 34
        versionCode = 16
        versionName = "3.0.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }

        // Backend base URL is set per build type below (v2.2.1 起两种构建类型
        // 都默认指生产公网端点; 本地联调在 App「设置」页覆盖 Base URL)。
    }

    signingConfigs {
        if (releaseStoreFile != null) {
            create("release") {
                storeFile = file(releaseStoreFile)
                storePassword = releaseSecret("RELEASE_STORE_PASSWORD")
                keyAlias = releaseSecret("RELEASE_KEY_ALIAS")
                keyPassword = releaseSecret("RELEASE_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
            // v2.2.1: debug 也默认指生产公网端点(此前指模拟器回环 10.0.2.2:8000,
            // 装在真机/别人手机上连不到任何东西)。本地联调用「设置」页改
            // Base URL, 或改回 10.0.2.2(模拟器)后自行构建。
            buildConfigField(
                "String",
                "BACKEND_BASE_URL",
                "\"http://118.89.58.84:5173/api/v1/\"",
            )
        }
        release {
            isMinifyEnabled = false
            if (signingConfigs.findByName("release") != null) {
                signingConfig = signingConfigs.getByName("release")
            }
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            // Production builds point at the public backend host (HTTP for now;
            // cleartext is permitted via AndroidManifest usesCleartextTraffic).
            // v2.1.0: backend deployed on :5173 (cloud firewall opens this port).
            buildConfigField(
                "String",
                "BACKEND_BASE_URL",
                "\"http://118.89.58.84:5173/api/v1/\"",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }

    testOptions {
        unitTests {
            isReturnDefaultValues = true
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons.extended)
    debugImplementation(libs.androidx.ui.tooling)

    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.androidx.hilt.navigation.compose)

    implementation(libs.retrofit)
    implementation(libs.retrofit.kotlinx.serialization)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.kotlinx.serialization.json)

    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)

    implementation(libs.androidx.media3.exoplayer)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.accompanist.permissions)
    implementation(libs.timber)
    implementation(libs.kotlinx.coroutines.android)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
}

detekt {
    buildUponDefaultConfig = true
    config.setFrom("$projectDir/config/detekt.yml")
}
