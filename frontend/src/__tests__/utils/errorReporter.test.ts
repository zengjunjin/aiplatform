import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  getErrorMessage,
  isFormValidationError,
  addBreadcrumb,
  getBreadcrumbs,
  clearBreadcrumbs,
  reportError,
} from '../../utils/errorReporter';

describe('errorReporter', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  describe('getErrorMessage', () => {
    it('should return message for Error instance', () => {
      expect(getErrorMessage(new Error('boom'))).toBe('boom');
    });

    it('should return string directly', () => {
      expect(getErrorMessage('plain string')).toBe('plain string');
    });

    it('should stringify other types', () => {
      expect(getErrorMessage(42)).toBe('42');
      expect(getErrorMessage({ a: 1 })).toBe('[object Object]');
      expect(getErrorMessage(null)).toBe('null');
    });
  });

  describe('isFormValidationError', () => {
    it('should return true for object with errorFields', () => {
      expect(isFormValidationError({ errorFields: [] })).toBe(true);
    });

    it('should return false for plain Error', () => {
      expect(isFormValidationError(new Error('x'))).toBe(false);
    });

    it('should return false for null', () => {
      expect(isFormValidationError(null)).toBe(false);
    });

    it('should return false for undefined', () => {
      expect(isFormValidationError(undefined)).toBe(false);
    });

    it('should return false for string', () => {
      expect(isFormValidationError('x')).toBe(false);
    });
  });

  describe('breadcrumb lifecycle', () => {
    it('addBreadcrumb should store crumb with timestamp', () => {
      addBreadcrumb({ type: 'route', message: 'navigated to /home' });
      const crumbs = getBreadcrumbs();
      expect(crumbs).toHaveLength(1);
      expect(crumbs[0].type).toBe('route');
      expect(crumbs[0].message).toBe('navigated to /home');
      expect(crumbs[0].timestamp).toBeGreaterThan(0);
    });

    it('addBreadcrumb should keep only last 10 crumbs', () => {
      for (let i = 0; i < 15; i++) {
        addBreadcrumb({ type: 'user', message: `action-${i}` });
      }
      const crumbs = getBreadcrumbs();
      expect(crumbs).toHaveLength(10);
      expect(crumbs[0].message).toBe('action-5');
      expect(crumbs[9].message).toBe('action-14');
    });

    it('getBreadcrumbs should return empty array when nothing stored', () => {
      expect(getBreadcrumbs()).toEqual([]);
    });

    it('clearBreadcrumbs should remove all crumbs', () => {
      addBreadcrumb({ type: 'api', message: 'GET /test' });
      addBreadcrumb({ type: 'error', message: 'failed' });
      clearBreadcrumbs();
      expect(getBreadcrumbs()).toEqual([]);
    });

    it('addBreadcrumb should handle data field', () => {
      addBreadcrumb({ type: 'api', message: 'POST /x', data: { status: 500 } });
      const crumbs = getBreadcrumbs();
      expect(crumbs[0].data).toEqual({ status: 500 });
    });
  });

  describe('reportError', () => {
    it('should log to console.error and add breadcrumb', () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
      const err = new Error('test error');
      err.name = 'TestError';
      reportError(err, { componentStack: 'at Component' } as any);

      expect(spy).toHaveBeenCalled();
      const crumbs = getBreadcrumbs();
      expect(crumbs).toHaveLength(1);
      expect(crumbs[0].type).toBe('error');
      expect(crumbs[0].message).toContain('TestError: test error');
      expect(crumbs[0].data).toHaveProperty('componentStack', 'at Component');

      spy.mockRestore();
    });

    it('should work without errorInfo', () => {
      const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
      reportError(new Error('no info'));

      const crumbs = getBreadcrumbs();
      expect(crumbs).toHaveLength(1);

      spy.mockRestore();
    });
  });

  describe('localStorage failure resilience', () => {
    it('addBreadcrumb should not throw when localStorage throws', () => {
      const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('quota');
      });
      expect(() => addBreadcrumb({ type: 'error', message: 'x' })).not.toThrow();
      spy.mockRestore();
    });

    it('getBreadcrumbs should return empty array when localStorage throws', () => {
      const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('denied');
      });
      expect(getBreadcrumbs()).toEqual([]);
      spy.mockRestore();
    });

    it('clearBreadcrumbs should not throw when localStorage throws', () => {
      const spy = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
        throw new Error('denied');
      });
      expect(() => clearBreadcrumbs()).not.toThrow();
      spy.mockRestore();
    });
  });
});
