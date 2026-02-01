# -*- coding: utf-8 -*-
"""Excel PowerQuery 刷新执行器"""

import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from executors.base import BaseExecutor, ExecutorResult


class ExcelExecutor(BaseExecutor):
    """Excel PowerQuery 刷新执行器
    
    使用 win32com 打开 Excel 文件并刷新所有数据连接。
    """
    
    def execute(
        self,
        script_path: str,
        args: List[str] = None,
        cwd: str = None,
        env: Dict[str, str] = None,
        log_dir: Path = None,
        timeout: int = None,
        **kwargs
    ) -> ExecutorResult:
        """刷新 Excel 文件中的 PowerQuery
        
        Args:
            script_path: Excel 文件路径 (.xlsx, .xlsm)
            args: 未使用
            cwd: 未使用
            env: 未使用
            log_dir: 日志目录
            timeout: 超时时间（秒），默认 300 秒
            
        Returns:
            ExecutorResult: 执行结果
        """
        # 解析路径
        excel_path = self.get_absolute_path(script_path)
        if not excel_path.exists():
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"Excel 文件不存在: {excel_path}"
            )
        
        # 检查文件扩展名
        if excel_path.suffix.lower() not in ('.xlsx', '.xlsm', '.xlsb', '.xls'):
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"不支持的文件格式: {excel_path.suffix}"
            )
        
        # 准备日志目录
        if log_dir is None:
            from config import LOG_DIR
            log_dir = LOG_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        stdout_path = log_dir / "stdout.txt"
        stderr_path = log_dir / "stderr.txt"
        
        # 默认超时 5 分钟
        if timeout is None:
            timeout = 300
        
        start_time = datetime.now()
        log_messages = []
        error_messages = []
        
        try:
            import pythoncom
            import win32com.client
            
            # 初始化 COM
            pythoncom.CoInitialize()
            
            log_messages.append(f"[{datetime.now().isoformat()}] 开始刷新 Excel: {excel_path}")
            log_messages.append(f"[{datetime.now().isoformat()}] 超时设置: {timeout} 秒")
            
            # 启动 Excel
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            
            try:
                # 打开工作簿
                log_messages.append(f"[{datetime.now().isoformat()}] 正在打开工作簿...")
                workbook = excel.Workbooks.Open(str(excel_path))
                
                # 设置连接刷新属性
                for conn in workbook.Connections:
                    try:
                        conn.OLEDBConnection.BackgroundQuery = False
                    except Exception:
                        pass
                
                # 刷新所有数据
                log_messages.append(f"[{datetime.now().isoformat()}] 正在刷新数据连接...")
                workbook.RefreshAll()
                
                # 等待刷新完成
                start_wait = time.time()
                while True:
                    try:
                        # 尝试访问工作簿，如果还在刷新会阻塞
                        _ = workbook.Sheets.Count
                        break
                    except Exception:
                        if time.time() - start_wait > timeout:
                            raise TimeoutError(f"刷新超时 ({timeout}秒)")
                        time.sleep(1)
                
                # 保存并关闭
                log_messages.append(f"[{datetime.now().isoformat()}] 正在保存工作簿...")
                workbook.Save()
                workbook.Close(SaveChanges=True)
                
                log_messages.append(f"[{datetime.now().isoformat()}] 刷新完成")
                
            finally:
                # 关闭 Excel
                try:
                    excel.Quit()
                except Exception:
                    pass
                
                # 释放 COM 对象
                del excel
                pythoncom.CoUninitialize()
            
            end_time = datetime.now()
            
            # 写入日志
            with open(stdout_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(log_messages))
            
            return ExecutorResult(
                success=True,
                exit_code=0,
                start_time=start_time,
                end_time=end_time,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path)
            )
            
        except ImportError as e:
            error_messages.append(f"缺少依赖: {e}")
            error_messages.append("请安装 pywin32: pip install pywin32")
            
        except TimeoutError as e:
            error_messages.append(str(e))
            
        except Exception as e:
            error_messages.append(f"刷新失败: {e}")
        
        end_time = datetime.now()
        
        # 写入日志
        with open(stdout_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(log_messages))
        with open(stderr_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(error_messages))
        
        return ExecutorResult(
            success=False,
            exit_code=1,
            start_time=start_time,
            end_time=end_time,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error_message='\n'.join(error_messages)
        )
    
    def validate(self, script_path: str) -> bool:
        """验证 Excel 文件路径"""
        if not script_path:
            return False
        path = Path(script_path)
        if not path.exists():
            return False
        return path.suffix.lower() in ('.xlsx', '.xlsm', '.xlsb', '.xls')
