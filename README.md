# 视频压缩工具

本仓库现在包含两套互不替代的入口：

- 原有 Linux Bash 脚本：继续用于服务器批量压缩和夜间调度。
- 新增跨平台桌面应用源码：面向采集人员，在 Windows/macOS 上选择目录后逐文件原位压缩。

桌面应用说明见 [`desktop_app/README.md`](desktop_app/README.md)，打包说明见
[`packaging/README.md`](packaging/README.md)。桌面版当前只负责压缩，不包含百度网盘上传。

使用 FFmpeg 批量压缩 MP4/MOV 视频，提供两种处理方式：

- 输出到独立目录，保留原文件。
- 在源目录内压缩并替换原文件。

还包含一组基于 cron 和 tmux 的夜间启停脚本。

## 当前状态

当前服务器已经具备以下依赖：

- FFmpeg 4.4.2
- ffprobe
- tmux 3.2a
- GNU xargs 4.8.0
- flock 2.37.2

项目中的 Shell 脚本已通过 bash 语法检查。2026-08-17 已用 40 个真实 MP4 副本完成原位端到端验证：40 个文件全部压缩、校验并生成报告，未修改原始视频目录。当前没有安装 cron。

## 目录结构

~~~text
video_compression/
├── compression/
│   ├── batch_compress_in_place.sh
│   ├── batch_compress_raw_videos.sh
│   └── reporting.sh
├── scheduling/
│   ├── nightly_start.sh
│   └── nightly_stop.sh
└── tools/
    ├── metrics_tee.sh
    ├── run_with_metrics.sh
    └── runtime_metrics.sh
~~~

## 编码参数

两个压缩脚本使用相同的核心参数：

~~~text
编码器：       libx264
编码速度：     preset fast
质量：         CRF 18
像素格式：     yuv420p
容器优化：     +faststart
音频：         不保留
输入流：       只处理第一个视频流
~~~

CRF 18 是高质量有损压缩，不是无损压缩。脚本会丢弃音频、DJI djmd/dbgi 私有数据流以及其他附加视频流，仅保留第一个视频流和部分容器级 metadata。

## 推荐用法：输出到独立目录

第一次处理一批数据时，优先使用该模式。源文件不会被修改。

~~~bash
cd /path/to/video_compression

./compression/batch_compress_raw_videos.sh \
  "/path/to/源视频目录" \
  "/path/to/压缩后视频目录" \
  2
~~~

三个参数依次是：

1. 源目录。
2. 输出目录。
3. 并发数，省略时默认为 3。

输出目录会保留源目录内部的相对结构，并生成：

~~~text
输出目录/
├── 原有目录结构和压缩视频
├── _logs/
└── broken_sources.txt
~~~

重要限制：输出目录不能位于源目录内部，否则扫描过程可能再次发现刚生成的输出文件。

如果目标视频已经存在且 ffprobe 检测到的包数与源文件一致，脚本会跳过；如果包数不同，会重新编码。

## 原位压缩

该模式会在校验成功后替换原文件，只应在确认备份、权限和磁盘空间后使用。

~~~bash
cd /path/to/video_compression

./compression/batch_compress_in_place.sh \
  "/path/to/待压缩视频目录" \
  2
~~~

两个参数依次是：

1. 视频根目录。
2. 并发数，省略时默认为 8。

每个文件的处理过程是：

~~~text
ffprobe 检查源文件
  -> 在源文件旁生成 *.compress_tmp.MP4
  -> FFmpeg 重编码
  -> 校验源文件和临时文件的包数
  -> mv 替换原文件
  -> 写入 done.txt
~~~

临时文件和原文件位于同一文件系统，因此成功后的 mv 替换不会经历跨文件系统复制。编码失败或校验失败时，原文件不会被替换。

### 状态与日志

默认状态目录是：

~~~text
~/tmp/video_compression/
~~~

其中包含：

~~~text
inplace_meta/<源路径标识>/
├── done.txt
├── broken_sources.txt
└── logs/
~~~

可以用环境变量指定其他状态目录：

~~~bash
VIDEO_COMPRESSION_STATE_DIR="$HOME/tmp/my_video_state" \
  ./compression/batch_compress_in_place.sh "/path/to/待压缩目录" 2
~~~

查看各任务完成数量：

~~~bash
find "$HOME/tmp/video_compression/inplace_meta" \
  -name done.txt -exec wc -l {} \;
~~~

done.txt 中已经记录的路径不会再次处理。如果需要使用不同参数重新压缩，不要直接复用原状态目录；应指定一个新的 VIDEO_COMPRESSION_STATE_DIR，并先确认这样做不会造成二次有损压缩。

### 70 Mbps 跳过规则

原位脚本会把视频码率低于 70 Mbps 的文件视为“疑似已经压缩”，写入 done.txt 后跳过。这个规则是启发式判断：

- 可以防止已经压缩过的视频被重复压缩。
- 也可能误跳过原本就是低码率的原始视频。

正式处理前应先用 ffprobe 抽样检查输入码率。

~~~bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,bit_rate \
  -of default=noprint_wrappers=1 \
  "/path/to/sample.MP4"
~~~

## 压缩报告

每次脚本正常结束后都会生成一份 TSV 报告。即使部分视频失败，只要主脚本能够完成收尾，报告仍会写入汇总，并通过 run_exit_code 标明本次运行是否存在错误。

独立输出版的报告位置：

~~~text
<输出目录>/_reports/compression_report_<时间>_<进程号>.tsv
~~~

原位版的报告位置：

~~~text
~/tmp/video_compression/inplace_meta/<源路径标识>/reports/
~~~

每个视频会记录：

- 处理状态、源路径和输出路径。
- 原始码率与压缩后码率，单位为 bps 和 Mbps。
- 原始体积与压缩后体积，单位为字节和 MiB。
- 节省的字节数、MiB 和百分比。
- 是否计入本次总体统计。
- 失败或跳过原因。

文件末尾的 SUMMARY 区域记录：

- 本次报告的文件数和可比较文件数。
- 原始总体积。
- 压缩后总体积。
- 总节省体积。
- 总节省百分比。
- 各状态的文件数量。
- 本次运行退出码。

报告是制表符分隔文件，可以直接使用 less、column、awk、Python、LibreOffice 或 Excel 打开。例如：

~~~bash
column -s $'\t' -t < "/path/to/compression_report.tsv" | less -S
~~~

查找汇总：

~~~bash
grep '^#' "/path/to/compression_report.tsv"
~~~

原位模式中，SKIPPED_DONE 表示文件在此前运行中已经完成。由于原文件已经被替换，本次运行无法重新得到其压缩前指标，因此该行不会计入本次总体积。新压缩成功和低码率跳过的文件会正常计入汇总。

如果主脚本被 SIGKILL、服务器掉电或终端被强制终止，可能留下只有逐文件记录、没有 SUMMARY 的部分报告。

## 可选运行指标

直接运行两个压缩脚本时，不会启动资源采样，也不会生成运行指标文件。需要诊断耗时或资源占用时，用独立包装器启动：

~~~bash
cd /path/to/video_compression

VIDEO_COMPRESSION_STATE_DIR="$HOME/tmp/my_video_state" \
  ./tools/run_with_metrics.sh \
  "$HOME/tmp/my_video_metrics" \
  "in_place_test" \
  -- ./compression/batch_compress_in_place.sh "/path/to/待压缩目录" 1
~~~

前两个包装器参数分别是指标输出目录和本次运行标签，`--` 后面是原本要执行的完整命令。默认每 5 秒采样一次；需要调整时可设置 `VIDEO_COMPRESSION_METRICS_INTERVAL`。

每次运行会生成：

- `run_summary_*.txt`：真实墙钟总耗时、退出码、CPU/内存/GPU峰值和平均值。
- `stage_summary_*.tsv`：初始化、扫描、源探测、编码、输出校验、替换与报告生成等阶段汇总。
- `phase_events_*.tsv`：每个视频每个阶段的明细耗时和状态。
- `resource_samples_*.tsv`：按时间采样的进程树 CPU、RSS、系统负载、可用内存和 GPU 数据。
- `time_verbose_*.txt`：GNU `time -v` 的最大常驻内存、CPU 时间、上下文切换和 I/O 统计。
- `command_*.log`：本次命令的完整标准输出和错误输出。

`tree_cpu_percent` 是压缩命令整个进程树的 CPU 百分比总和，多核运行时可以超过 100%。GPU 平均利用率、峰值和总显存是整台共享服务器的系统值，可能包含其他用户的任务；`process_tree_gpu_memory_mib` 只匹配本命令进程树，更适合判断压缩任务自身是否使用 GPU。当前 libx264 编码走 CPU，正常情况下该值应为 0。

## 夜间调度

夜间脚本不在仓库中保存真实数据路径。运行或配置 cron 前设置：

~~~bash
export VIDEO_COMPRESSION_SOURCE_DIR="/path/to/待压缩目录"
export VIDEO_COMPRESSION_JOBS=1
~~~

可选变量 `VIDEO_COMPRESSION_SESSION` 用于修改 tmux 会话名，默认是
`video_compression_nightly`。`VIDEO_COMPRESSION_JOBS` 默认是 1。

手动启动：

~~~bash
./scheduling/nightly_start.sh
~~~

查看后台会话：

~~~bash
tmux attach -t video_compression_nightly
~~~

从 tmux 界面退出但保持任务运行：

~~~text
按 Ctrl-b，然后按 d
~~~

手动停止并清理未完成临时文件：

~~~bash
./scheduling/nightly_stop.sh
~~~

### 安装 cron

不要在没有核对目标路径和资源占用时直接安装。

首先创建日志目录：

~~~bash
mkdir -p "$HOME/tmp/video_compression/nightly_logs"
~~~

然后运行：

~~~bash
crontab -e
~~~

加入：

~~~cron
0 23 * * * VIDEO_COMPRESSION_SOURCE_DIR="/path/to/待压缩目录" VIDEO_COMPRESSION_JOBS=1 /path/to/video_compression/scheduling/nightly_start.sh >> "$HOME/tmp/video_compression/nightly_logs/cron_stderr.log" 2>&1
0 9 * * * VIDEO_COMPRESSION_SOURCE_DIR="/path/to/待压缩目录" /path/to/video_compression/scheduling/nightly_stop.sh >> "$HOME/tmp/video_compression/nightly_logs/cron_stderr.log" 2>&1
~~~

cron 不属于项目代码，安装后需要通过 crontab -l 单独检查。

## 使用经验

### 先用独立输出模式

对于新数据，先压缩到独立目录并抽样检查画质、帧率、时长和下游算法结果。确认满足需求后，再考虑原位压缩。

### 从低并发开始

每个 xargs worker 都会启动一个 FFmpeg，而 libx264 自身还会使用多个 CPU 线程。在共享服务器上建议先显式传入并发数 1 或 2，不要直接依赖原位脚本的默认并发 8。

可以用以下命令观察资源：

~~~bash
ps -eo pid,etimes,pcpu,pmem,cmd | grep -E "ffmpeg|batch_compress"
~~~

### 预留临时空间

原位压缩过程中，原文件和压缩临时文件会同时存在。NAS 必须至少能容纳当前并发任务生成的全部临时文件。

### 不要同时启动两套任务

不要对同一源目录同时运行两个手动压缩进程。done.txt 不是严格的跨进程锁，两个独立任务可能同时处理同一文件。

夜间启动脚本只通过配置的 tmux 会话名避免重复启动，无法发现所有手动启动方式。

### 理解校验范围

脚本使用 ffprobe 的视频包数做完整性判断：

- 独立输出版要求包数严格相等。
- 原位版允许相差不超过 50。

该检查能发现明显失败，但不等价于逐帧完整解码，也不能证明画面质量满足业务需求。

### 中断和续传

原位任务中断后，已经写入 done.txt 的文件会跳过；未完成的 *.compress_tmp.MP4 会在下次处理同一文件前删除并重新生成。

使用 nightly_stop.sh 停止时，会结束配置的 tmux 会话，并清理
`VIDEO_COMPRESSION_SOURCE_DIR` 中的临时压缩文件。

## 上线前检查

在处理真实目录前至少确认：

1. 输入和输出路径没有写反。
2. 独立输出目录不在源目录内部。
3. 已抽样确认视频码率、编码和附加数据流。
4. 接受删除音频及 DJI 私有数据流。
5. 有足够的 NAS 空间保存临时文件。
6. 并发数适合当前共享服务器负载。
7. 原位模式的数据已有备份或可以重新获取。
8. 调度脚本中的目标目录确实是本次任务目录。
