import os
import h5py
import torch
import numpy as np
from ms_model_estimation.training.dataset.TorchDataset import TorchDataset
from ms_model_estimation.training.dataset.data_loading import load_and_transform3d
from ms_model_estimation.training.utils.BMLUtils import MIRROR_JOINTS


class BMLImgDataSet(TorchDataset):

    def __init__(
            self, cfg, h5pyBMLFolder, cameraParamter, dataseType, evaluation=True, useEveryFrame=False,
            usePredefinedSeed=False
    ):
        super(BMLImgDataSet, self).__init__(cfg, evaluation=evaluation)
        np.random.seed(self.cfg.SEED)

        self.evaluation = evaluation

        self.h5pyBMLFolder = h5pyBMLFolder
        self.useEveryFrame = useEveryFrame
        self.cameraParamter = cameraParamter
        self.usePredefinedSeed = usePredefinedSeed

        self.usedSubjects = []
        if dataseType == 0:
            self.usedSubjects = self.cfg.TRAINING_SUBJECTS
            #self.data = np.load(h5pyBMLFolder + "prediction_train.npy", allow_pickle=True).item()
        elif dataseType == 1:
            self.usedSubjects = self.cfg.VALID_SUBJECTS
            #self.data = np.load(h5pyBMLFolder + "prediction_valid.npy", allow_pickle=True).item()
        elif dataseType == 2:
            self.usedSubjects = self.cfg.TEST_SUBJECTS
            #self.data = np.load(h5pyBMLFolder + "prediction_test.npy", allow_pickle=True).item()
        else:
            raise Exception("The type of the dataset are not defined")

        self.usedEachFrame = self.cfg.DATASET.TRAINING_USEDEACHFRAME if not self.evaluation else self.cfg.DATASET.USEDEACHFRAME
        self.create_mapping()
        # self.awaredOcclusion = AwaredOcclusion(cfg)

    def create_mapping(self):

        # create mapping to idx : [subjectID, cameraType, index of local hdf5]

        globalDataIdx = 0
        self.usedIndices = []
        for subject in self.usedSubjects:
            if os.path.exists(self.h5pyBMLFolder + f'subject_{subject}.hdf5'):
                with h5py.File(self.h5pyBMLFolder + f'subject_{subject}.hdf5', 'r') as f:
                    globalFrames = f["globalFrame"][:]
                    cameraTypes = f["cameraType"][:]
                    usedFrames = f['usedFrame'][:]
                for localIdx, globalFrame in enumerate(globalFrames):
                    if self.useEveryFrame or (globalFrame % self.usedEachFrame) == 0 and (
                            self.evaluation or usedFrames[localIdx]):
                        self.usedIndices.append([(subject), cameraTypes[localIdx].decode(), localIdx, globalDataIdx])
                    globalDataIdx += 1
        self.usedIndices = self.usedIndices

    def __getitem__(self, idx):

        if torch.is_tensor(idx):
            idx = idx.tolist()

        subjectID, cameraType, localIdx, globalDataIdx = self.usedIndices[idx]

        with h5py.File(self.h5pyBMLFolder + f'subject_{subjectID}.hdf5', 'r') as f:
            pos3d = f['pos3d'][localIdx, :self.cfg.PREDICTION.NUM_JOINTS, :]
            marker_pose3d = f['marker_pos3d'][localIdx, :, :]
            bbox = f['bbox'][localIdx, :]
            globalFrame = f['globalFrame'][localIdx]
            hflipUsage = f['hflipUsage'][localIdx]
            seed = f['seed'][localIdx]

        # concatenate the joint and the marker
        pos3d = np.concatenate((pos3d, marker_pose3d), axis=0)

        # get camera
        camera = self.cameraParamter[cameraType].copy()

        with h5py.File(self.h5pyBMLFolder + f'{subjectID}_{cameraType}_img.hdf5', 'r') as f:
            image = f["images"][globalFrame, :, :, :][:, :, [2, 1, 0]]

        if self.usePredefinedSeed:
            # data augmentation
            image, pos3d, pos2d, joint3d_validity_mask, _, _ = load_and_transform3d(
                self.cfg, image, bbox, pos3d, camera, MIRROR_JOINTS, evaluation=self.evaluation, hflipUsage=hflipUsage,
                #seed=seed
            )
        else:
            image, pos3d, pos2d, joint3d_validity_mask, _, _ = load_and_transform3d(
                self.cfg, image, bbox, pos3d, camera, MIRROR_JOINTS, evaluation=self.evaluation
            )

        # occulsionMask = self.awaredOcclusion.measure_occlusion(pos3d)
        # occulsionMask = self.data["labelOcclusion"][globalDataIdx, 50:50 + self.cfg.TRAINING.NUMPRED]

        sample = {
            'image': image / 255, 'pose3d': pos3d,
            'pose2d': pos2d, "bbox": bbox, 'joint3d_validity_mask': joint3d_validity_mask,
            'localIdx': localIdx, 'fileIdx': globalDataIdx
        }

        if self.transform:
            sample = self.transform(sample)

        sample["pose3d"].requires_grad = False
        sample["pose2d"].requires_grad = False
        sample["joint3d_validity_mask"].requires_grad = False
        sample["bbox"].requires_grad = False
        sample["image"].requires_grad = False

        return sample

    def __len__(self):

        return len(self.usedIndices)
