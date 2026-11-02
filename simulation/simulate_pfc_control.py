"""
Simulação Comparativa de Controle em Cascata para Boost PFC:
1. Linearização por Mudança de Base (Espaço de Estados em Energia / Tensão ao Quadrado: x = v_dc^2)
2. Linearização por Jacobiano (Pequenos Sinais em Tensão: x = v_dc)

Parâmetros baseados no projeto de hardware 'Active Boost PFC 380V':
- L = 2.2 mH
- C = 200 uF (2x 100uF / 450V)
- Vin = 127 V_rms @ 60 Hz
- Vdc_ref = 380 V
- Potência Nominal: 500 W (degrau para 1000 W)
"""

import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

class PFCParameters:
    def __init__(self):
        # Parâmetros de Potência e Rede
        self.L = 2.2e-3             # Indutor Boost: 2.2 mH
        self.C = 200e-6             # Banco de saída: 200 uF
        self.Vrms = 127.0           # Tensão de entrada RMS: 127 V
        self.f_grid = 60.0          # Frequência da rede: 60 Hz
        self.omega_grid = 2 * np.pi * self.f_grid
        self.Vpeak = np.sqrt(2) * self.Vrms
        self.Vdc_nom = 380.0        # Tensão nominal de saída: 380 V
        self.P_nom = 500.0          # Carga nominal: 500 W
        self.RL_nom = (self.Vdc_nom ** 2) / self.P_nom  # ~288.8 Ohms

        # Especificações do Controle
        # Malha Interna de Corrente: Banda ~2.5 kHz
        self.f_i = 2500.0
        self.omega_i = 2 * np.pi * self.f_i
        self.K1 = self.L * self.omega_i  # ~34.56 V/A

        # Malha Externa de Tensão/Energia: Banda ~12 Hz (deve ser bem menor que 120 Hz para filtrar ripple)
        self.f_v = 12.0
        self.omega_v = 2 * np.pi * self.f_v
        self.zeta_v = 0.707

        # Ganhos para Controle por Energia (x = v_dc^2)
        # Planta linear: dx/dt + (2/(RL*C))*x = (2*Vrms^2/C)*g
        self.K3_E = self.C * (self.omega_v ** 2) / (2 * self.Vrms ** 2)
        self.K2_E = self.C * (2 * self.zeta_v * self.omega_v - 2 / (self.RL_nom * self.C)) / (2 * self.Vrms ** 2)

        # Ganhos para Controle por Jacobiano (x = v_dc)
        # Linearizado em Vdc0: d(v_dc^2) = 2*Vdc0*d(v_dc) => K_J = 2*Vdc0 * K_E
        self.K3_J = 2 * self.Vdc_nom * self.K3_E
        self.K2_J = 2 * self.Vdc_nom * self.K2_E


def run_simulation(pfc: PFCParameters, control_mode: str, scenario: str = 'startup_and_load'):
    """
    Executa a simulação do conversor Boost PFC no domínio do tempo.
    control_mode: 'energy' (x = v_dc^2) ou 'jacobian' (x = v_dc)
    scenario:
        - 'startup_and_load': Partida de Vin_pk (180V) até 380V, depois degrau de carga (500W -> 1000W)
        - 'reference_step': Operando em 380V, degraus de referência (+30V e -50V)
    """
    dt = 2e-5  # Passo de 20 us (suficiente para dinâmica de corrente e ripple de 120Hz)
    
    if scenario == 'startup_and_load':
        t_end = 0.8
        t = np.arange(0, t_end, dt)
        v_init = np.sqrt(2) * pfc.Vrms  # Tensão inicial pré-carregada pela ponte de diodos (~180V)
    elif scenario == 'reference_step':
        t_end = 0.8
        t = np.arange(0, t_end, dt)
        v_init = pfc.Vdc_nom
    else:
        raise ValueError("Cenário inválido")

    N = len(t)
    
    # Variáveis de estado
    i_L = 0.0
    v_dc = v_init
    chi = 0.0  # Estado do integrador
    
    # Vetores de log
    v_dc_arr = np.zeros(N)
    v_ref_arr = np.zeros(N)
    i_L_arr = np.zeros(N)
    i_ref_arr = np.zeros(N)
    g_arr = np.zeros(N)
    vin_arr = np.zeros(N)
    d_arr = np.zeros(N)
    
    # Anti-windup e limites práticos
    g_max = 0.15  # Condutância máxima sintetizável (limita corrente de pico)
    
    for k in range(N):
        curr_t = t[k]
        
        # Tensão de entrada retificada
        vin_instant = np.abs(pfc.Vpeak * np.sin(pfc.omega_grid * curr_t))
        vin_arr[k] = vin_instant
        
        # Definição do cenário
        if scenario == 'startup_and_load':
            v_ref = pfc.Vdc_nom
            # Degrau de carga em t = 0.4s: 500W -> 1000W (RL_nom -> RL_nom / 2)
            # Retorno em t = 0.65s: 1000W -> 500W
            if curr_t < 0.4:
                R_load = pfc.RL_nom
            elif curr_t < 0.65:
                R_load = pfc.RL_nom / 2.0
            else:
                R_load = pfc.RL_nom
        elif scenario == 'reference_step':
            R_load = pfc.RL_nom
            # Degrau de referência: 380V -> 410V em 0.2s, 410V -> 350V em 0.5s
            if curr_t < 0.2:
                v_ref = 380.0
            elif curr_t < 0.5:
                v_ref = 410.0
            else:
                v_ref = 350.0
                
        v_ref_arr[k] = v_ref

        # ========================================================
        # MALHA EXTERNA (Tensão / Energia)
        # ========================================================
        if control_mode == 'energy':
            x = v_dc ** 2
            x_ref = v_ref ** 2
            err = x - x_ref
            g_raw = -pfc.K2_E * err - pfc.K3_E * chi
        else: # jacobian
            x = v_dc
            x_ref = v_ref
            err = x - x_ref
            g_raw = -pfc.K2_J * err - pfc.K3_J * chi

        # Saturação da condutância sintetizada e anti-windup no integrador
        g = np.clip(g_raw, 0.0, g_max)
        if g_raw == g:  # Atualiza integrador apenas se não saturou (anti-windup por clamping)
            chi += err * dt

        # Síntese da corrente de referência (Resistência Emulada)
        i_ref = vin_instant * g
        
        # ========================================================
        # MALHA INTERNA (Controle por Linearização com Realimentação)
        # (1 - u) = (vin + K1*(i - i_ref) - p) / v_dc
        # ========================================================
        p = 0.0  # p = L * d(i_ref)/dt (desprezível dada a alta banda da malha interna)
        v_dc_safe = max(v_dc, 15.0)  # Evita divisão por zero
        
        one_minus_u = (vin_instant + pfc.K1 * (i_L - i_ref) - p) / v_dc_safe
        # Saturação física da razão cíclica complementar (1 - u) in [0.02, 1.0] => u in [0, 0.98]
        one_minus_u = np.clip(one_minus_u, 0.02, 1.0)
        u = 1.0 - one_minus_u
        
        # ========================================================
        # EQUAÇÕES DE ESTADO DO CONVERSOR BOOST (Modelo Médio)
        # ========================================================
        di_L = (vin_instant - one_minus_u * v_dc) / pfc.L
        dv_dc = (one_minus_u * i_L - v_dc / R_load) / pfc.C
        
        # Integração numérica (Forward Euler com passo pequeno)
        i_L += di_L * dt
        if i_L < 0.0:  # Condução contínua com diodo retificador/boost (não permite corrente reversa)
            i_L = 0.0
            
        v_dc += dv_dc * dt
        # Condição de condução natural dos diodos: v_dc nunca cai abaixo da tensão instantânea da rede
        if v_dc < vin_instant:
            v_dc = vin_instant
            
        # Gravação para telemetria
        v_dc_arr[k] = v_dc
        i_L_arr[k] = i_L
        i_ref_arr[k] = i_ref
        g_arr[k] = g
        d_arr[k] = u
        
    return {
        't': t,
        'v_dc': v_dc_arr,
        'v_ref': v_ref_arr,
        'i_L': i_L_arr,
        'i_ref': i_ref_arr,
        'g': g_arr,
        'vin': vin_arr,
        'd': d_arr
    }


def compute_metrics(res, pfc: PFCParameters, t_start=0.0, t_end=0.8):
    """Calcula métricas quantitativas de desempenho."""
    idx = (res['t'] >= t_start) & (res['t'] <= t_end)
    t = res['t'][idx]
    v = res['v_dc'][idx]
    v_ref = res['v_ref'][idx]
    i = res['i_L'][idx]
    
    # Sobressinal máximo relativo ao patamar de 380V
    max_v = np.max(v)
    overshoot_pct = max(0.0, (max_v - 380.0) / 380.0 * 100.0)
    
    # Subtensão mínima no degrau de carga (para t entre 0.4s e 0.65s)
    load_step_idx = (res['t'] >= 0.4) & (res['t'] <= 0.65)
    if np.any(load_step_idx):
        min_v_load = np.min(res['v_dc'][load_step_idx])
        sag_pct = (380.0 - min_v_load) / 380.0 * 100.0
    else:
        sag_pct = 0.0
        
    # Pico de corrente no indutor
    peak_current = np.max(i)
    
    # Erro absoluto integral (IAE)
    iae = np.trapezoid(np.abs(v - v_ref), t)
    
    # THD e Fator de Potência no regime permanente (últimos 4 ciclos de 60Hz: ~66.7 ms)
    ss_idx = res['t'] >= (res['t'][-1] - 4 / pfc.f_grid)
    i_ss = res['i_L'][ss_idx]
    vin_ss = res['vin'][ss_idx]
    
    # Como i_L e vin estão retificados: p_in = mean(vin * i)
    p_in = np.mean(vin_ss * i_ss)
    v_rms_calc = np.sqrt(np.mean(vin_ss ** 2))
    i_rms_calc = np.sqrt(np.mean(i_ss ** 2))
    pf = p_in / (v_rms_calc * i_rms_calc) if (v_rms_calc * i_rms_calc) > 0 else 0
    
    return {
        'overshoot_pct': overshoot_pct,
        'sag_pct': sag_pct,
        'peak_current': peak_current,
        'iae': iae,
        'pf': pf
    }


def main():
    pfc = PFCParameters()
    print("=" * 70)
    print("SIMULAÇÃO COMPARATIVA: CONTROLE EM CASCATA PFC ATIVO 380V")
    print(f"Hardware: L = {pfc.L*1e3:.1f} mH, C = {pfc.C*1e6:.0f} uF, Vin = {pfc.Vrms:.0f} Vrms, Vdc = {pfc.Vdc_nom:.0f} V")
    print(f"Ganhos Calculados:")
    print(f" - Malha Interna: K1 = {pfc.K1:.2f} V/A (Banda = {pfc.f_i:.0f} Hz)")
    print(f" - Base Energia:   K2_E = {pfc.K2_E:.4e}, K3_E = {pfc.K3_E:.4e}")
    print(f" - Base Jacobiano: K2_J = {pfc.K2_J:.4e}, K3_J = {pfc.K3_J:.4e}")
    print("=" * 70)

    # 1. Simulação Cenário 1: Partida + Degrau de Carga (500W -> 1000W -> 500W)
    print("\n[1/2] Executando Cenário 1: Partida e Variação de Carga...")
    res_energy_sc1 = run_simulation(pfc, 'energy', 'startup_and_load')
    res_jacob_sc1 = run_simulation(pfc, 'jacobian', 'startup_and_load')
    
    m_energy_sc1 = compute_metrics(res_energy_sc1, pfc)
    m_jacob_sc1 = compute_metrics(res_jacob_sc1, pfc)

    # 2. Simulação Cenário 2: Degraus de Tensão de Referência (380V -> 410V -> 350V)
    print("[2/2] Executando Cenário 2: Degraus de Tensão de Referência...")
    res_energy_sc2 = run_simulation(pfc, 'energy', 'reference_step')
    res_jacob_sc2 = run_simulation(pfc, 'jacobian', 'reference_step')
    
    m_energy_sc2 = compute_metrics(res_energy_sc2, pfc)
    m_jacob_sc2 = compute_metrics(res_jacob_sc2, pfc)

    # Impressão dos Resultados
    print("\n" + "=" * 70)
    print("TABELA COMPARATIVA DE DESEMPENHO (Cenário 1: Partida + Carga 500W -> 1000W)")
    print("=" * 70)
    print(f"{'Métrica':<35} | {'Energia (x = v_dc^2)':<16} | {'Jacobiano (x = v_dc)':<16}")
    print("-" * 73)
    print(f"{'Sobressinal na Partida (%)':<35} | {m_energy_sc1['overshoot_pct']:<16.2f} | {m_jacob_sc1['overshoot_pct']:<16.2f}")
    print(f"{'Afundamento no Degrau de Carga (%)':<35} | {m_energy_sc1['sag_pct']:<16.2f} | {m_jacob_sc1['sag_pct']:<16.2f}")
    print(f"{'Pico de Corrente Máximo (A)':<35} | {m_energy_sc1['peak_current']:<16.2f} | {m_jacob_sc1['peak_current']:<16.2f}")
    print(f"{'Erro Absoluto Integral - IAE (V.s)':<35} | {m_energy_sc1['iae']:<16.2f} | {m_jacob_sc1['iae']:<16.2f}")
    print(f"{'Fator de Potência em Regime (PF)':<35} | {m_energy_sc1['pf']:<16.4f} | {m_jacob_sc1['pf']:<16.4f}")
    print("=" * 70)

    # GERAÇÃO DOS GRÁFICOS
    print("\nGerando figuras comparativas de alta resolução...")
    
    fig, axes = plt.subplots(3, 2, figsize=(16, 11), dpi=150)
    fig.suptitle('Comparação de Desempenho do PFC Boost: Base em Energia ($v_{dc}^2$) vs Jacobiano ($v_{dc}$)', fontsize=14, fontweight='bold')

    # (0, 0) - Cenário 1: Tensão no Barramento CC
    ax = axes[0, 0]
    ax.plot(res_energy_sc1['t'], res_energy_sc1['v_ref'], 'k--', label='$V_{dc,ref}$ (380V)', alpha=0.7)
    ax.plot(res_energy_sc1['t'], res_energy_sc1['v_dc'], 'b-', label='Controle por Energia ($x = v_{dc}^2$)', linewidth=1.8)
    ax.plot(res_jacob_sc1['t'], res_jacob_sc1['v_dc'], 'r--', label='Controle por Jacobiano ($x = v_{dc}$)', linewidth=1.6)
    ax.set_ylabel('Tensão no Barramento $V_{dc}$ [V]', fontweight='bold')
    ax.set_title('Cenário 1: Partida e Degraus de Carga (500W $\\rightarrow$ 1000W $\\rightarrow$ 500W)', fontsize=11, fontweight='bold')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(loc='lower right')
    ax.axvspan(0.4, 0.65, color='orange', alpha=0.1, label='Carga = 1000W')

    # (1, 0) - Cenário 1: Corrente no Indutor
    ax = axes[1, 0]
    ax.plot(res_energy_sc1['t'], res_energy_sc1['i_L'], 'b-', label='Corrente $i_L$ (Energia)', linewidth=1.2, alpha=0.85)
    ax.plot(res_jacob_sc1['t'], res_jacob_sc1['i_L'], 'r--', label='Corrente $i_L$ (Jacobiano)', linewidth=1.0, alpha=0.75)
    ax.set_ylabel('Corrente do Indutor $i_L$ [A]', fontweight='bold')
    ax.set_title('Envoltória e Picos de Corrente do Indutor', fontsize=11, fontweight='bold')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(loc='upper right')

    # (2, 0) - Cenário 1: Condutância Sintetizada g(t)
    ax = axes[2, 0]
    ax.plot(res_energy_sc1['t'], res_energy_sc1['g'], 'b-', label='Condutância $g(t)$ (Energia)', linewidth=1.8)
    ax.plot(res_jacob_sc1['t'], res_jacob_sc1['g'], 'r--', label='Condutância $g(t)$ (Jacobiano)', linewidth=1.6)
    ax.set_xlabel('Tempo [s]', fontweight='bold')
    ax.set_ylabel('Condutância $g(t)$ [S]', fontweight='bold')
    ax.set_title('Ação de Controle da Malha Externa ($g = i_{ref} / v_{in}$)', fontsize=11, fontweight='bold')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(loc='upper right')

    # (0, 1) - Cenário 2: Degraus de Referência de Tensão
    ax = axes[0, 1]
    ax.plot(res_energy_sc2['t'], res_energy_sc2['v_ref'], 'k--', label='Referência $V_{ref}(t)$', alpha=0.7)
    ax.plot(res_energy_sc2['t'], res_energy_sc2['v_dc'], 'b-', label='Energia ($x = v_{dc}^2$)', linewidth=1.8)
    ax.plot(res_jacob_sc2['t'], res_jacob_sc2['v_dc'], 'r--', label='Jacobiano ($x = v_{dc}$)', linewidth=1.6)
    ax.set_ylabel('Tensão no Barramento $V_{dc}$ [V]', fontweight='bold')
    ax.set_title('Cenário 2: Degraus de Referência (380V $\\rightarrow$ 410V $\\rightarrow$ 350V)', fontsize=11, fontweight='bold')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(loc='lower right')

    # (1, 1) - Cenário 2: Erro de Rastreamento (Vdc - Vref)
    ax = axes[1, 1]
    err_E = res_energy_sc2['v_dc'] - res_energy_sc2['v_ref']
    err_J = res_jacob_sc2['v_dc'] - res_jacob_sc2['v_ref']
    ax.plot(res_energy_sc2['t'], err_E, 'b-', label='Erro $e(t)$ (Energia)', linewidth=1.8)
    ax.plot(res_jacob_sc2['t'], err_J, 'r--', label='Erro $e(t)$ (Jacobiano)', linewidth=1.6)
    ax.axhline(0, color='black', linestyle=':', alpha=0.5)
    ax.set_ylabel('Erro $V_{dc} - V_{ref}$ [V]', fontweight='bold')
    ax.set_title('Erro Dinâmico de Rastreamento (Simetria de Resposta)', fontsize=11, fontweight='bold')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(loc='upper right')

    # (2, 1) - Zoom em Regime Permanente: Tensão e Corrente da Rede (PFC Ativo)
    ax = axes[2, 1]
    zoom_idx = (res_energy_sc1['t'] >= 0.72) & (res_energy_sc1['t'] <= 0.77)
    t_zoom = res_energy_sc1['t'][zoom_idx] * 1000 # ms
    vin_norm = res_energy_sc1['vin'][zoom_idx] / pfc.Vpeak
    i_norm_E = res_energy_sc1['i_L'][zoom_idx] / np.max(res_energy_sc1['i_L'][zoom_idx])
    ax.plot(t_zoom, vin_norm, 'k-', label='$v_{in}(t)$ Normalizada (Rede)', linewidth=1.8, alpha=0.6)
    ax.plot(t_zoom, i_norm_E, 'b-', label='$i_L(t)$ Normalizada (Energia)', linewidth=1.8)
    ax.set_xlabel('Tempo [ms]', fontweight='bold')
    ax.set_ylabel('Amplitude Normalizada [p.u.]', fontweight='bold')
    ax.set_title('Zoom em Regime (3 Ciclos): Rastreamento em Fase (Fator de Potência ~ 1)', fontsize=11, fontweight='bold')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(loc='upper right')

    plt.tight_layout()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    docs_dir = os.path.join(project_root, 'docs')
    os.makedirs(docs_dir, exist_ok=True)
    output_path = os.path.join(docs_dir, 'pfc_control_comparison.png')
    plt.savefig(output_path, dpi=200)
    print(f"Gráfico comparativo salvo com sucesso em: {output_path}")

if __name__ == '__main__':
    main()
