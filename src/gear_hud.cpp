// Crazy Taxi's D/R gear display, drawn in the bottom-right corner.
//
// speed.exe v1.3 keeps its IDirect3DDevice9* at 0x00982BDC (MWSDK host.hpp, reference confidence). The main frame
// flip (in 0x006E6E40's caller) ends the scene, then:
//   006E75D9 call 0x006C0910   ; frame timing bookkeeping, called from nowhere else
//   006E75EA call [ecx + 0x44] ; IDirect3DDevice9::Present
// That call is redirected so the display is drawn over the finished frame right before it is presented. It runs
// every frame, menus included, so it also keeps the player's settings in line (player_settings.cpp). Hooking
// Present in the device's vtable instead only lasted a moment next to other mods that hook it too.
// The textures come from build/gear_display, embedded at build time by tools/hud/gear_textures.py.
#include "gear_hud.h"

#include <windows.h>

#include <d3d9.h>

#include <atomic>
#include <cstdint>
#include <cstring>

#include "config.h"
#include "gear_textures.h"
#include "log.h"
#include "patch.h"
#include "player_settings.h"

namespace ctmw {

namespace {

constexpr std::uintptr_t kD3D9Device = 0x00982BDC;
constexpr std::uintptr_t kFlipCallFrameTiming = 0x006E75D9;
constexpr std::uintptr_t kFrameTiming = 0x006C0910;
// The display hides once the handling has not driven the car for this long.
constexpr ULONGLONG kShowMs = 200;

using FrameTimingFn = void(__cdecl*)();
FrameTimingFn g_orig_frame_timing = nullptr;

std::atomic<ULONGLONG> g_last_update{0};
std::atomic<bool> g_reverse{false};

// Created on the render thread, for the device they belong to.
IDirect3DDevice9* g_tex_device = nullptr;
IDirect3DTexture9* g_tex_drive = nullptr;
IDirect3DTexture9* g_tex_reverse = nullptr;

IDirect3DTexture9* make_texture(IDirect3DDevice9* dev, const std::uint32_t* pixels, int w, int h) {
    IDirect3DTexture9* tex = nullptr;
    // Managed, so it survives a device Reset.
    if (FAILED(dev->CreateTexture(w, h, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &tex, nullptr))) return nullptr;
    D3DLOCKED_RECT lr;
    if (FAILED(tex->LockRect(0, &lr, nullptr, 0))) {
        tex->Release();
        return nullptr;
    }
    for (int y = 0; y < h; ++y) std::memcpy(static_cast<char*>(lr.pBits) + y * lr.Pitch, pixels + y * w, w * 4);
    tex->UnlockRect(0);
    return tex;
}

bool textures_for(IDirect3DDevice9* dev) {
    if (dev != g_tex_device) {
        if (g_tex_drive) g_tex_drive->Release();
        if (g_tex_reverse) g_tex_reverse->Release();
        g_tex_drive = make_texture(dev, kGearDrive, kGearDriveWidth, kGearDriveHeight);
        g_tex_reverse = make_texture(dev, kGearReverse, kGearReverseWidth, kGearReverseHeight);
        g_tex_device = dev;
        if (!g_tex_drive || !g_tex_reverse) log("gear_hud: could not create the textures");
    }
    return g_tex_drive && g_tex_reverse;
}

// Logs the first failure of each kind, so a display that never shows can be traced.
void fail_once(const char* what, HRESULT hr) {
    static const char* last = nullptr;
    if (what == last) return;
    last = what;
    log("gear_hud: %s failed (%08x); display skipped", what, static_cast<unsigned>(hr));
}

void draw(IDirect3DDevice9* dev) {
    HRESULT hr = dev->TestCooperativeLevel();
    if (hr != D3D_OK) return fail_once("TestCooperativeLevel", hr);
    if (!textures_for(dev)) return;

    IDirect3DSurface9* back = nullptr;
    if (FAILED(hr = dev->GetBackBuffer(0, 0, D3DBACKBUFFER_TYPE_MONO, &back))) return fail_once("GetBackBuffer", hr);
    D3DSURFACE_DESC desc;
    back->GetDesc(&desc);

    IDirect3DStateBlock9* saved = nullptr;
    if (FAILED(hr = dev->CreateStateBlock(D3DSBT_ALL, &saved))) {
        back->Release();
        return fail_once("CreateStateBlock", hr);
    }
    // State blocks leave out the render target and depth buffer, so those are kept by hand.
    IDirect3DSurface9* old_rt = nullptr;
    IDirect3DSurface9* old_ds = nullptr;
    dev->GetRenderTarget(0, &old_rt);
    dev->GetDepthStencilSurface(&old_ds);
    dev->SetRenderTarget(0, back);
    dev->SetDepthStencilSurface(nullptr);

    if (FAILED(hr = dev->BeginScene())) {
        fail_once("BeginScene", hr);
    } else {
        const D3DVIEWPORT9 vp{0, 0, desc.Width, desc.Height, 0, 1};
        dev->SetViewport(&vp);
        dev->SetVertexShader(nullptr);
        dev->SetPixelShader(nullptr);
        dev->SetFVF(D3DFVF_XYZRHW | D3DFVF_TEX1);
        dev->SetRenderState(D3DRS_ZENABLE, FALSE);
        dev->SetRenderState(D3DRS_STENCILENABLE, FALSE);
        dev->SetRenderState(D3DRS_SCISSORTESTENABLE, FALSE);
        dev->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
        dev->SetRenderState(D3DRS_LIGHTING, FALSE);
        dev->SetRenderState(D3DRS_FOGENABLE, FALSE);
        dev->SetRenderState(D3DRS_ALPHATESTENABLE, FALSE);
        dev->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
        dev->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
        dev->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
        dev->SetRenderState(D3DRS_BLENDOP, D3DBLENDOP_ADD);
        dev->SetRenderState(D3DRS_COLORWRITEENABLE, 0xF);
        dev->SetRenderState(D3DRS_SRGBWRITEENABLE, FALSE);
        dev->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
        dev->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
        dev->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
        dev->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
        dev->SetTextureStageState(0, D3DTSS_TEXCOORDINDEX, 0);
        dev->SetTextureStageState(0, D3DTSS_TEXTURETRANSFORMFLAGS, D3DTTFF_DISABLE);
        dev->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE);
        dev->SetTextureStageState(1, D3DTSS_ALPHAOP, D3DTOP_DISABLE);
        dev->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
        dev->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
        dev->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE);
        dev->SetSamplerState(0, D3DSAMP_ADDRESSU, D3DTADDRESS_CLAMP);
        dev->SetSamplerState(0, D3DSAMP_ADDRESSV, D3DTADDRESS_CLAMP);
        dev->SetTexture(0, g_reverse ? g_tex_reverse : g_tex_drive);

        // Sizes are in 1/480ths of the screen height, like Crazy Taxi's 480-line HUD.
        const Hud& hud = g_config.hud;
        const float unit = desc.Height / 480.0f;
        const float x1 = desc.Width - hud.gear_right * unit - 0.5f, y1 = desc.Height - hud.gear_bottom * unit - 0.5f;
        const float x0 = x1 - hud.gear_size * unit, y0 = y1 - hud.gear_size * unit;
        struct Vertex {
            float x, y, z, rhw, u, v;
        };
        const Vertex quad[] = {{x0, y0, 0, 1, 0, 0}, {x1, y0, 0, 1, 1, 0}, {x0, y1, 0, 1, 0, 1}, {x1, y1, 0, 1, 1, 1}};
        dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, quad, sizeof(Vertex));
        dev->EndScene();
    }

    dev->SetRenderTarget(0, old_rt);
    dev->SetDepthStencilSurface(old_ds);
    if (old_rt) old_rt->Release();
    if (old_ds) old_ds->Release();
    saved->Apply();
    saved->Release();
    back->Release();
}

void __cdecl on_frame_timing() {
    g_orig_frame_timing();
    auto* dev = *reinterpret_cast<IDirect3DDevice9**>(va(kD3D9Device));
    const bool shown = g_config.hud.gear_display && dev && GetTickCount64() - g_last_update < kShowMs;
    player_settings_force(shown);
    if (shown) draw(dev);
}

}  // namespace

bool gear_hud_install() {
    const std::uintptr_t orig = redirect_call(kFlipCallFrameTiming, kFrameTiming,
                                              reinterpret_cast<const void*>(&on_frame_timing));
    if (!orig) {
        log("gear_hud: frame flip is not stock; no gear display or forced settings");
        return false;
    }
    g_orig_frame_timing = reinterpret_cast<FrameTimingFn>(orig);
    log("gear_hud: installed");
    return true;
}

void gear_hud_update(bool reverse) {
    g_reverse = reverse;
    g_last_update = GetTickCount64();
}

}  // namespace ctmw
