from datetime import datetime
from PIL import Image
import torch
import numpy as np
from pathlib import Path
import cv2
from .networks import UNet
from .utils import local_maxima, make_pgt, optimum, target_peaks_gen, remove_outside_plot
import argparse
import os
import random


def parse_args(step, test_path):
    """
  Parse input arguments
  """
    parser = argparse.ArgumentParser(description="Train data path")
    parser.add_argument(
        "-i",
        "--input_path",
        dest="input_path",
        help="dataset's path",
        default=test_path,
        type=str,
    )
    parser.add_argument(
        "-o",
        "--output_path",
        dest="output_path",
        help="output path",
        default="/home/hyeonwoo/research/Experiment1/All_Result/Detection/step{}".format(str(step)),
        type=str,
    )
    parser.add_argument(
        "-w",
        "--weight_path",
        dest="weight_path",
        help="load weight path",
        default="/home/hyeonwoo/research/Experiment1/Model/Detection/step{}/best.pth".format(str(step)),
    )
    parser.add_argument(
        "-g", "--gpu", dest="gpu", help="whether use CUDA", default=True, action="store_true"
    )

    args = parser.parse_args()
    return args


class Predict:
    def __init__(self, args):
        self.net = args.net
        self.gpu = args.gpu

        self.ori_path = args.input_path

        self.save_ori_path = args.output_path / Path("ori")
        self.save_pred_path = args.output_path / Path("pred")

        self.save_ori_path.mkdir(parents=True, exist_ok=True)
        self.save_pred_path.mkdir(parents=True, exist_ok=True)

    def pred(self, ori):
        img = (ori.astype(np.float32) / 255).reshape(
            (1, ori.shape[0], ori.shape[1])
            )

        with torch.no_grad():
            #numpy to tensor
            img = torch.from_numpy(img).unsqueeze(0)
            if self.gpu:
                img = img.cuda()
            mask_pred = self.net(img)
        #tesor to numpy
        pre_img = mask_pred.detach().cpu().numpy()[0, 0]
        pre_img = (pre_img * 255).astype(np.uint8)
        return pre_img

    def main(self):
        self.net.eval()
        # path def
        paths = sorted(self.ori_path.glob("*.tif"))
        for i, path in enumerate(paths):
            #ori = np.array(Image.open(path))
            ori = cv2.imread(str(path), 0)
            pre_img = self.pred(ori)
            cv2.imwrite(str(self.save_pred_path / Path(os.path.basename(path))), pre_img)
            cv2.imwrite(str(self.save_ori_path / Path(os.path.basename(path))), ori)


class PredictFmeasure(Predict):
    def __init__(self, args):
        super().__init__(args)
        self.ori_path = args.input_path / Path("ori")
        self.gt_path = args.input_path / Path("gt")

        self.save_gt_path = args.output_path / Path("gt")
        self.save_pgt_path = args.output_path / Path("pgt")
        #self.save_error_path = args.output_path / Path("error")
        self.save_txt_path = args.output_path / Path("f-measure.txt")

        self.save_gt_path.mkdir(parents=True, exist_ok=True)
        self.save_pgt_path.mkdir(parents=True, exist_ok=True)
        self.save_error_path.mkdir(parents=True, exist_ok=True)

        self.peak_thresh = 100
        self.dist_peak = 2
        self.dist_threshold = 10

        self.tps = 0
        self.fps = 0
        self.fns = 0


    def cal_tp_fp_fn(self, ori, gt_img, pre_img, i, ori_path):
        #정답이미지에서 픽셀255인 좌표찾기
        #gt = target_peaks_gen((gt_img).astype(np.uint8))
        gt = local_maxima(gt_img, self.peak_thresh, self.dist_peak)
        #예측 이미지에서 밝기가 가장 밝은 곳의 중심좌표찾기
        res = local_maxima(pre_img, self.peak_thresh, self.dist_peak)
        associate_id = optimum(gt, res, self.dist_threshold)

        gt_final, no_detected_id = remove_outside_plot(
            gt, associate_id, 0, pre_img.shape
        )
        res_final, overdetection_id = remove_outside_plot(
            res, associate_id, 1, pre_img.shape
        )


        cv2.imwrite(str(self.save_pred_path / Path(os.path.basename(ori_path))), pre_img)
        cv2.imwrite(str(self.save_ori_path / Path(os.path.basename(ori_path))), ori)
        cv2.imwrite(str(self.save_gt_path / Path(os.path.basename(ori_path))), gt_img)
        #cv2.imwrite(str(self.save_pgt_path / Path(os.path.basename(ori_path))), pgt_img)


        #truepositive
        tp = associate_id.shape[0]
        #falsenegative
        fn = gt_final.shape[0] - associate_id.shape[0]
        #falsepositive
        fp = res_final.shape[0] - associate_id.shape[0]
        self.tps += tp
        self.fns += fn
        self.fps += fp


    def main(self):
        self.net.eval()
        # path def
        path_x = sorted(self.ori_path.glob("*.tif"))
        path_y = sorted(self.gt_path.glob("*.tif"))
        print(path_x)
        z = zip(path_x, path_y)

        for i, b in enumerate(z):
            import gc

            gc.collect()
            ori = cv2.imread(str(b[0]), 0)
            gt_img = cv2.imread(str(b[1]), 0)

            pre_img = self.pred(ori)
            #pgt_img = make_pgt(pre_img, threshold=100, dist=4)
            self.cal_tp_fp_fn(ori, gt_img, pre_img, i, str(b[0]))
        if self.tps == 0:
            recall = 0
            precision = 0
            f_measure = 0
        else:
            recall = self.tps / (self.tps + self.fns)
            precision = self.tps / (self.tps + self.fps)
            f_measure = (2 * recall * precision) / (recall + precision)

        print(precision, recall, f_measure)
        with self.save_txt_path.open(mode="a") as f:
            f.write("%f,%f,%f\n" % (precision, recall, f_measure))


def f_score(step, test_path):
    args = parse_args(step, test_path)

    args.input_path = Path(args.input_path)
    args.output_path = Path(args.output_path)

    net = UNet(n_channels=1, n_classes=1)
    device = torch.device('cuda:0')
    net.load_state_dict(torch.load(args.weight_path, map_location=device))

    if args.gpu:
        net.cuda()
    args.net = net

    pred = PredictFmeasure(args)

    pred.main()
