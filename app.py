import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import copy
import psutil
from datetime import datetime, timedelta

# --- CONFIGURATION & CMOS CONSTANTS ---
C_CAPACITANCE = 0.1  # Switching capacitance (Fixed)
STATIC_POWER = 0.2   # Leakage power in Watts (Fixed)
VOLTAGE_MAP = {3.5: 1.2, 2.5: 1.0, 1.2: 0.8} # Frequency to Voltage mapping
MAX_FREQ = 3.5
MAX_VOLT = 1.2
TIME_QUANTUM = 4 

class PCB:
    def __init__(self, pid, arrival, burst, deadline, priority, name="Unknown"):
        self.pid = f"{pid} ({name})"
        self.at = arrival
        self.bt = burst
        self.rt = burst 
        self.deadline = deadline
        self.priority = priority
        self.energy = 0.0

def get_power(freq, volt):
    # Core Formula: P = C * V^2 * f + P_static
    return (C_CAPACITANCE * (volt**2) * freq) + STATIC_POWER

def get_live_processes(limit=8):
    """Fetches real processes and compresses arrival times for simulation visualization."""
    tasks = []
    # Fetch active processes
    procs = sorted(psutil.process_iter(['pid', 'name', 'cpu_percent', 'create_time', 'nice']), 
                   key=lambda x: x.info['cpu_percent'] if x.info['cpu_percent'] is not None else 0, 
                   reverse=True)
    
    raw_data = []
    for p in procs:
        try:
            info = p.info
            # STRICT FILTER: Ignore PID 4 (System), PID 0 (Idle), and missing/invalid creation times
            if info['create_time'] is None or info['pid'] <= 4 or info['create_time'] < 1000000:
                continue

            raw_at = info['create_time']
            cpu_val = info.get('cpu_percent')
            bt = max(int(cpu_val), 1) if cpu_val is not None else 1
            nice_val = info.get('nice') if info.get('nice') is not None else 0
            pr = max(1, min(5, (nice_val + 20) // 8))
            
            raw_data.append({
                'pid': info['pid'],
                'raw_at': raw_at,
                'bt': bt,
                'pr': pr,
                'name': info['name'][:10]
            })
            
            if len(raw_data) >= limit: 
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if not raw_data:
        return []

    # Sort by the actual OS creation time so the chronological order is historically accurate
    raw_data.sort(key=lambda x: x['raw_at'])

    # SIMULATION SCALING: Space the arrivals out by 1 to 3 seconds instead of days
    simulated_arrival_time = 0
    for i, item in enumerate(raw_data):
        # Synthesize a deadline based on the compressed arrival time
        dl = simulated_arrival_time + item['bt'] + 25 
        
        tasks.append(PCB(
            pid=item['pid'], 
            arrival=simulated_arrival_time, 
            burst=item['bt'], 
            deadline=dl, 
            priority=item['pr'], 
            name=item['name']
        ))
        
        # Increment the next arrival time slightly for the next process in queue
        simulated_arrival_time += (i % 3) + 1  

    return tasks

def simulate_all(tasks):
    results = {}
    
    # 1. FCFS Simulation
    fcfs_tasks = copy.deepcopy(tasks)
    fcfs_tasks.sort(key=lambda x: x.at)
    time_clock, energy, logs = 0, 0.0, []
    for t in fcfs_tasks:
        if time_clock < t.at: time_clock = t.at
        p = get_power(MAX_FREQ, MAX_VOLT)
        e = p * t.bt
        logs.append({"Task": t.pid, "Start": time_clock, "Finish": time_clock + t.bt, "Freq": "3.5GHz"})
        energy += e
        time_clock += t.bt
    results['FCFS'] = {"energy": round(energy, 2), "logs": logs}

    # 2. SJF Simulation
    sjf_tasks = copy.deepcopy(tasks)
    time_clock, energy, logs = 0, 0.0, []
    completed = []
    while len(completed) < len(sjf_tasks):
        ready = [t for t in sjf_tasks if t.at <= time_clock and t not in completed]
        if not ready: 
            time_clock = min([t.at for t in sjf_tasks if t not in completed])
            continue
        ready.sort(key=lambda x: x.bt)
        t = ready[0]
        p = get_power(MAX_FREQ, MAX_VOLT)
        e = p * t.bt
        logs.append({"Task": t.pid, "Start": time_clock, "Finish": time_clock + t.bt, "Freq": "3.5GHz"})
        energy += e
        time_clock += t.bt
        completed.append(t)
    results['SJF'] = {"energy": round(energy, 2), "logs": logs}

    # 3. Priority Scheduling
    ps_tasks = copy.deepcopy(tasks)
    time_clock, energy, logs = 0, 0.0, []
    completed = []
    while len(completed) < len(ps_tasks):
        ready = [t for t in ps_tasks if t.at <= time_clock and t not in completed]
        if not ready:
            time_clock = min([t.at for t in ps_tasks if t not in completed])
            continue
        ready.sort(key=lambda x: x.priority) 
        t = ready[0]
        p = get_power(MAX_FREQ, MAX_VOLT)
        e = p * t.bt
        logs.append({"Task": t.pid, "Start": time_clock, "Finish": time_clock + t.bt, "Freq": "3.5GHz"})
        energy += e
        time_clock += t.bt
        completed.append(t)
    results['Priority'] = {"energy": round(energy, 2), "logs": logs}

    # 4. Round Robin
    rr_tasks = copy.deepcopy(tasks)
    time_clock, energy, logs = 0, 0.0, []
    queue = []
    rr_tasks.sort(key=lambda x: x.at)
    remaining = len(rr_tasks)
    idx = 0
    while remaining > 0:
        while idx < len(rr_tasks) and rr_tasks[idx].at <= time_clock:
            queue.append(rr_tasks[idx])
            idx += 1
        if not queue:
            time_clock = min([t.at for t in rr_tasks if t.at > time_clock])
            continue
        t = queue.pop(0)
        exec_time = min(t.rt, TIME_QUANTUM)
        p = get_power(MAX_FREQ, MAX_VOLT)
        energy += (p * exec_time)
        logs.append({"Task": t.pid, "Start": time_clock, "Finish": time_clock + exec_time, "Freq": "3.5GHz"})
        time_clock += exec_time
        t.rt -= exec_time
        while idx < len(rr_tasks) and rr_tasks[idx].at <= time_clock:
            queue.append(rr_tasks[idx])
            idx += 1
        if t.rt > 0: queue.append(t)
        else: remaining -= 1
    results['Round Robin'] = {"energy": round(energy, 2), "logs": logs}

    # 5. Our Heuristic Engine (DVFS Algorithm)
    h_tasks = copy.deepcopy(tasks)
    time_clock, energy, logs = 0, 0.0, []
    completed = []
    while len(completed) < len(h_tasks):
        ready = [t for t in h_tasks if t.at <= time_clock and t not in completed]
        if not ready:
            time_clock = min([t.at for t in h_tasks if t not in completed])
            continue
        ready.sort(key=lambda x: x.deadline) 
        t = ready[0]
        slack = t.deadline - (time_clock + t.bt)
        
        # Heuristic Logic for Frequency Selection based on Slack
        if slack > 15: f, v = 1.2, 0.8
        elif slack > 7: f, v = 2.5, 1.0
        else: f, v = 3.5, 1.2
        
        p = get_power(f, v)
        e = p * t.bt
        logs.append({"Task": t.pid, "Start": time_clock, "Finish": time_clock + t.bt, "Freq": f"{f}GHz", "Volt": v})
        energy += e
        time_clock += t.bt
        completed.append(t)
    results['Our Engine'] = {"energy": round(energy, 2), "logs": logs}
    
    return results

# --- STREAMLIT UI ---
st.set_page_config(page_title="Live Energy-Efficient Scheduler", layout="wide")
st.title("⚡ Energy-Efficient CPU Scheduling Algorithm")
st.markdown("### Comparative Performance Analysis: Live Heuristic DVFS vs. Standards")

# Sidebar
st.sidebar.header("Data Source Configuration")
mode = st.sidebar.radio("Select Input Mode", ["Live CPU Resources", "Manual Input"])

tasks_input = []
if mode == "Manual Input":
    num = st.sidebar.slider("Number of Processes", 3, 8, 4)
    for i in range(num):
        with st.sidebar.expander(f"Process P{i+1}"):
            at = st.number_input("Arrival Time", 0, 50, i*2, key=f"at{i}")
            bt = st.number_input("Burst Time", 1, 20, 5, key=f"bt{i}")
            dl = st.number_input("Deadline", 1, 150, (i+1)*15, key=f"dl{i}")
            pr = st.number_input("Priority", 1, 5, 1, key=f"pr{i}")
            tasks_input.append(PCB(i+1, at, bt, dl, pr))
else:
    num_live = st.sidebar.slider("Live Processes to Fetch", 3, 15, 6)
    if st.sidebar.button("Fetch Fresh CPU Data"):
        st.session_state.live_tasks = get_live_processes(num_live)
    
    if 'live_tasks' in st.session_state:
        tasks_input = st.session_state.live_tasks
        st.sidebar.success(f"Captured {len(tasks_input)} active processes.")
    else:
        st.sidebar.warning("Click 'Fetch Fresh CPU Data' to start.")

if st.sidebar.button("Run Benchmark Analysis") and tasks_input:
    all_res = simulate_all(tasks_input)
    
    # Savings Calculation
    avg_std_energy = (all_res['FCFS']['energy'] + all_res['SJF']['energy'] + 
                      all_res['Round Robin']['energy'] + all_res['Priority']['energy']) / 4
    our_energy = all_res['Our Engine']['energy']
    savings_pct = round(((avg_std_energy - our_energy) / avg_std_energy) * 100, 2) if avg_std_energy > 0 else 0

    # --- TOP METRICS ---
    st.markdown("---")
    m_col = st.columns(6)
    m_col[0].metric("Avg. Std Energy", f"{round(avg_std_energy, 2)} J")
    m_col[1].metric("Our Engine", f"{our_energy} J")
    m_col[2].metric("Savings (%)", f"{savings_pct}%", delta=f"{savings_pct}%")
    m_col[3].metric("FCFS", f"{all_res['FCFS']['energy']} J")
    m_col[4].metric("SJF", f"{all_res['SJF']['energy']} J")
    m_col[5].metric("RR", f"{all_res['Round Robin']['energy']} J")

    # --- MATHEMATICAL METHODOLOGY ---
    st.subheader("📝 Mathematical Calculation & Methodology")
    c1, c2 = st.columns(2)
    with c1:
        st.info("**Standard Power Calculation**")
        st.latex(r"P_{std} = (C \cdot V_{max}^2 \cdot f_{max}) + P_{static}")
        st.write(f"Where $C=0.1$, $V=1.2V$, $f=3.5GHz$. Constant power: **{round(get_power(3.5, 1.2), 3)}W**")

    with c2:
        st.success("**Our Heuristic Engine (DVFS)**")
        st.latex(r"P_{i} = (C \cdot V_{i}^2 \cdot f_{i}) + P_{static}")
        st.write("Voltage and Frequency are scaled dynamically based on process slack time.")

    # Charts
    st.subheader("📊 Energy Consumption Benchmark")
    comp_df = pd.DataFrame([{"Algorithm": k, "Energy Consumption (J)": v['energy']} for k,v in all_res.items()])
    fig_bar = px.bar(comp_df, x="Algorithm", y="Energy Consumption (J)", color="Algorithm", text_auto=True)
    st.plotly_chart(fig_bar, use_container_width=True)

    # Timelines
    st.subheader("🕒 Execution Timelines (Live Snapshot)")
    tabs = st.tabs(["Our Heuristic Engine", "FCFS", "SJF", "Priority", "Round Robin"])
    algo_keys = ['Our Engine', 'FCFS', 'SJF', 'Priority', 'Round Robin']
    colors = {"1.2GHz": "#00CC96", "2.5GHz": "#636EFA", "3.5GHz": "#EF553B"}

    for i, key in enumerate(algo_keys):
        with tabs[i]:
            df = pd.DataFrame(all_res[key]['logs'])
            
            # FIX: Use a fixed arbitrary base date (Jan 1, 1970) to ensure uniform scaling
            base_date = datetime(1970, 1, 1)
            df['StartDT'] = df['Start'].apply(lambda x: base_date + timedelta(seconds=float(x)))
            df['FinishDT'] = df['Finish'].apply(lambda x: base_date + timedelta(seconds=float(x)))
            
            if key == 'Our Engine':
                fig = px.timeline(df, x_start="StartDT", x_end="FinishDT", y="Task", color="Freq", 
                                  text="Freq", color_discrete_map=colors, title=f"{key} Resource Allocation")
            else:
                fig = px.timeline(df, x_start="StartDT", x_end="FinishDT", y="Task", color="Task",
                                  title=f"{key} Performance Baseline")
            
            # Format X-axis to show MM:SS instead of full dates
            fig.update_layout(xaxis=dict(tickformat="%M:%S"))
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

    # Process Data Table
    st.subheader("📋 Captured Process Metrics")
    report_data = [{"PID/Name": t.pid, "Arrival": t.at, "Burst(CPU%)": t.bt, "Deadline": t.deadline, "Priority": t.priority} for t in tasks_input]
    st.table(pd.DataFrame(report_data))